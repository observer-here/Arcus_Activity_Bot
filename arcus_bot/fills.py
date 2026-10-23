from datetime import datetime, timezone

from arcus_bot.config import ADDR, REST


def parse_address(text):
    if not text or not ADDR.fullmatch(text):
        return None
    return text.lower()


def parse_indexes(token):
    if token is None:
        return [0]
    if token.lower() == "all":
        return list(range(10))
    if token.isdigit() and 0 <= int(token) <= 9:
        return [int(token)]
    return None


def esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short(address):
    return f"{address[:6]}…{address[-4:]}"


def when(created_at):
    if not created_at:
        return ""
    stamp = datetime.fromtimestamp(int(created_at) / 1_000_000, timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M:%S UTC")


async def fetch_fills(client, address, idx, limit=30, from_us=None):
    params = {"address": address, "accountIndex": idx, "limit": limit}
    if from_us:
        params["from"] = from_us
    resp = await client.get(f"{REST}/v1/fills", params=params, timeout=20)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return resp.json().get("fills") or []


def format_fill(address, idx, fill):
    liq = (fill.get("liquidation") or {}).get("method")
    title = f"{fill.get('side', '?')} {fill.get('marketDisplayName', '?')}"
    if liq:
        title += f" · {liq}"
    sub = f" · sub {idx}" if idx else ""
    effect = (fill.get("positionEffect") or "").replace("_", " ").lower()
    lines = [
        f"<b>{esc(title)}</b>",
        f"<code>{esc(short(address))}</code>{esc(sub)}",
        f"{esc(fill.get('size'))} @ {esc(fill.get('price'))} · {esc((fill.get('role') or '').lower())}",
        f"fee {esc(fill.get('fee') or '0')} · pnl {esc(fill.get('closedPnl') or '0')}",
    ]
    if effect:
        lines.append(esc(effect))
    stamp = when(fill.get("createdAt"))
    if stamp:
        lines.append(esc(stamp))
    return "\n".join(lines)
