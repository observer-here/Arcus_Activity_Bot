import time
from decimal import Decimal

from arcus_bot.config import ADDR, REST

_leverage = {}


def parse_address(text):
    if not text or not ADDR.fullmatch(text.strip()):
        return None
    return text.strip().lower()


def parse_indexes(token):
    if token is None:
        return [0]
    if token.lower() == "all":
        return list(range(10))
    if token.isdigit() and 0 <= int(token) <= 9:
        return [int(token)]
    return None


def short(address):
    return f"{address[:6]}…{address[-4:]}"


def dollars(value):
    n = Decimal(str(value))
    if n >= 10000:
        text = f"{n / Decimal(1000):.2f}".rstrip("0").rstrip(".")
        return f"${text}k"
    if n == n.to_integral_value():
        return f"${int(n)}"
    return f"${n:.2f}"


def entry_price(value):
    n = Decimal(str(value))
    if n >= 1000:
        return f"${n / Decimal(1000):.2f}k"
    if n >= 1:
        return f"${n:.2f}".rstrip("0").rstrip(".")
    return f"${n:.4f}".rstrip("0").rstrip(".")


def side_name(fill):
    effect = (fill.get("positionEffect") or "").upper()
    if effect in {"OPEN_LONG", "ADD_LONG", "CLOSE_LONG", "FLIP_SHORT_TO_LONG"}:
        return "long"
    if effect in {"OPEN_SHORT", "ADD_SHORT", "CLOSE_SHORT", "FLIP_LONG_TO_SHORT"}:
        return "short"
    return "long" if fill.get("side") == "BUY" else "short"


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


async def trade_card(client, address, idx, fill):
    market = fill.get("marketDisplayName") or "?"
    side = side_name(fill)
    size = Decimal(str(fill.get("size") or "0"))
    price = Decimal(str(fill.get("price") or "0"))
    value = size * price
    try:
        lev = await lookup_leverage(client, address, idx, fill.get("marketId"))
    except Exception:
        lev = None
    if lev:
        lev_text = f"{lev}x"
        margin_text = dollars(value / Decimal(lev))
    else:
        lev_text = "?"
        margin_text = "?"
    mark = "🟢" if side == "long" else "🔴"
    return "\n".join([
        f"{mark} Trade",
        f"ticker: ${market.split('-')[0]}",
        f"type: {side}",
        f"value: {dollars(value)}",
        f"lev: {lev_text}",
        f"margin: {margin_text}",
        f"entry: {entry_price(price)}",
    ])
