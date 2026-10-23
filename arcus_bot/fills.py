import asyncio
import time
from decimal import Decimal

from arcus_bot.config import ADDR, REST

_leverage = {}


def parse_address(text):
    if not text or not ADDR.fullmatch(text.strip()):
        return None
    return text.strip().lower()


def short(address):
    return f"{address[:6]}…{address[-4:]}"


def d(value):
    return Decimal(str(value or 0))


def dollars(value):
    n = d(value)
    if n >= 10000:
        text = f"{n / 1000:.2f}".rstrip("0").rstrip(".")
        return f"${text}k"
    if n == n.to_integral_value():
        return f"${int(n)}"
    return f"${n:.2f}"


def price_text(value):
    n = d(value)
    if n >= 1000:
        return f"${n / 1000:.2f}k"
    if n >= 1:
        return f"${n:.2f}".rstrip("0").rstrip(".")
    return f"${n:.4f}".rstrip("0").rstrip(".")


def signed(value):
    n = d(value).quantize(Decimal("0.01"))
    return f"{'-' if n < 0 else '+'}{dollars(abs(n))}"


def side_name(fill):
    effect = (fill.get("positionEffect") or "").upper()
    if effect in {"OPEN_LONG", "ADD_LONG", "CLOSE_LONG", "FLIP_SHORT_TO_LONG"}:
        return "long"
    if effect in {"OPEN_SHORT", "ADD_SHORT", "CLOSE_SHORT", "FLIP_LONG_TO_SHORT"}:
        return "short"
    return "long" if fill.get("side") == "BUY" else "short"


def merge_orders(fills):
    groups = {}
    for fill in fills:
        groups.setdefault(fill.get("orderId") or fill.get("tradeId"), []).append(fill)
    merged = []
    for rows in groups.values():
        size = sum(d(r.get("size")) for r in rows)
        notional = sum(d(r.get("size")) * d(r.get("price")) for r in rows)
        merged.append({
            **rows[0],
            "size": str(size),
            "price": str(notional / size) if size else rows[0].get("price"),
            "fee": str(sum(d(r.get("fee")) for r in rows)),
            "closedPnl": str(sum(d(r.get("closedPnl")) for r in rows)),
            "createdAt": max(int(r.get("createdAt") or 0) for r in rows),
        })
    return sorted(merged, key=lambda row: row["createdAt"])


async def fetch_fills(client, address, idx, limit=30, from_us=None):
    params = {"address": address, "accountIndex": idx, "limit": limit}
    if from_us:
        params["from"] = from_us
    resp = await client.get(f"{REST}/v1/fills", params=params, timeout=20)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return resp.json().get("fills") or []


async def lookup_leverage(client, address, idx, market_id):
    key = (address, idx)
    cached = _leverage.get(key)
    if not cached or time.time() - cached[0] > 60:
        resp = await client.get(
            f"{REST}/v1/leverages",
            params={"address": address, "accountIndex": idx},
            timeout=20,
        )
        resp.raise_for_status()
        mapping = {
            row["marketId"]: int(row["leverage"])
            for row in resp.json().get("leverages") or []
        }
        cached = (time.time(), mapping)
        _leverage[key] = cached
    return cached[1].get(market_id)


async def lookup_position(client, address, idx, market_id):
    resp = await client.get(
        f"{REST}/v1/positions",
        params={"address": address, "accountIndex": idx},
        timeout=20,
    )
    resp.raise_for_status()
    return (resp.json().get("positions") or {}).get(str(market_id))


async def active_subaccounts(client, address):
    async def has_activity(idx):
        resp = await client.get(
            f"{REST}/v1/account",
            params={"address": address, "accountIndex": idx},
            timeout=20,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    found = await asyncio.gather(*(has_activity(idx) for idx in range(10)))
    return [idx for idx, active in enumerate(found) if active] or [0]


async def safe(call):
    try:
        return await call
    except Exception:
        return None


async def trade_card(client, address, idx, fill):
    effect = (fill.get("positionEffect") or "").upper()
    action = effect.split("_")[0] or "OPEN"
    side = side_name(fill)
    market_id = fill.get("marketId")
    size, price = d(fill.get("size")), d(fill.get("price"))
    value = size * price
    pnl, fee = d(fill.get("closedPnl")), d(fill.get("fee"))
    lev = await safe(lookup_leverage(client, address, idx, market_id))
    pos = await safe(lookup_position(client, address, idx, market_id))

    entry = price
    if action == "ADD" and pos:
        entry = d(pos.get("averageEntryPrice"))
    elif action == "CLOSE" and size:
        gross = (pnl + fee) / size
        entry = price - gross if side == "long" else price + gross

    if action == "CLOSE":
        left = d(pos.get("size")) if pos else 0
        title = "Reduced" if left > 0 else "Closed"
        icon = "✅" if pnl >= 0 else "❌"
    elif action == "FLIP":
        title, icon = "Flipped", "🔄"
    else:
        title, icon = ("Added", "➕") if action == "ADD" else ("Opened", "📌")

    lines = [
        f"{icon} {title}",
        f"ticker: {'🟢' if side == 'long' else '🔴'} ${(fill.get('marketDisplayName') or '?').split('-')[0]}",
        f"value: {dollars(value)}",
        f"lev: {f'{lev}x' if lev else '?'}",
    ]
    if action in {"OPEN", "ADD"}:
        lines.append(f"margin: {dollars(value / lev) if lev else '?'}")
        lines.append(f"entry: {price_text(entry)}")
        if action == "ADD" and pos:
            lines.append(f"total: {dollars(abs(d(pos.get('positionValueNotional'))))}")
    elif action == "CLOSE":
        lines.append(f"entry: {price_text(entry)}")
        lines.append(f"exit: {price_text(price)}")
        margin = entry * size / lev if lev else 0
        roi = ""
        if margin:
            pct = pnl / margin * 100
            roi = f" ({'-' if pct < 0 else '+'}{abs(pct):.1f}%)"
        lines.append(f"pnl: {signed(pnl)}{roi}")
        if title == "Reduced":
            lines.append(f"left: {dollars(abs(d(pos.get('positionValueNotional'))))}")
    else:
        lines.append(f"pnl: {signed(pnl)}")
    return "\n".join(lines)
