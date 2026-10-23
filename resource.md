# Arcus mainnet activity

Telegram bot that watches Ethereum addresses and alerts on Arcus perpetual fills. Reads are public. No API key and no wallet key.

Docs index: https://docs.arcus.xyz/llms.txt

## Layout

```
arcus_bot/config.py     mainnet hosts, env, limits
arcus_bot/store.py      sqlite watches and seen fills
arcus_bot/fills.py      REST fills and message text
arcus_bot/watch.py      userFills websocket
arcus_bot/handlers.py   telegram commands
arcus_bot/__main__.py   process entry
data/watches.db         created on first run
```

## Run

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

`.env` in the project root:

```
TELEGRAM_BOT_TOKEN=123456:abc
```

```
.venv\Scripts\python -m arcus_bot
```

Commands: `/add 0xaddress`, `/add 0xaddress 3`, `/add 0xaddress all`, `/remove 0xaddress`, `/list`, `/fills 0xaddress`.

`/add` marks the latest fills as already seen. Alerts start at the next fill. Subaccount index is `0-9`. Default is `0`.

## Hosts

| | REST | WebSocket |
| --- | --- | --- |
| Mainnet | `https://api.arcus.xyz` | `wss://api.arcus.xyz/v1/ws` |
| Testnet | `https://api.testnet.arcus.xyz` | `wss://api.testnet.arcus.xyz/v1/ws` |

This bot is pinned to mainnet. Chain id for API-key registration (only needed to place orders) is `4663` mainnet, `46630` testnet.

`GET /health` is the liveness check. `GET /v1/time` returns server time in Unix nanoseconds.

## Fills this bot uses

`GET /v1/fills?address=0x...&accountIndex=0&limit=5`

Optional: `market`, `side` (`BUY`/`SELL`), `role` (`maker`/`taker`), `from`, `to`. `from` and `to` are epoch microseconds, same unit as `createdAt`. No auth header. `404` means no activity. List weight is 20 plus a per-row charge.

A fill row:

| Field | Meaning |
| --- | --- |
| `tradeId` | Stable id. Dedup key. |
| `orderId` | Order that filled |
| `marketId` / `marketDisplayName` | Market. `1` is BTC-USD. Ids are not a dense sequence. |
| `side` | `BUY` or `SELL` |
| `size` / `price` | This execution, decimal strings |
| `originalSize` / `remainingSize` | Parent order size |
| `fee` | Fee in quote. Liquidation penalty lives here when forced. |
| `closedPnl` | Realized pnl for the fill, net of trading fee |
| `role` | `MAKER`, `TAKER`, or `ALP` |
| `positionEffect` | `OPEN_LONG`, `ADD_LONG`, `CLOSE_SHORT`, `FLIP_LONG_TO_SHORT`, and the short-side twins |
| `createdAt` | Epoch microseconds |
| `liquidation` | Present on forced closes. `method` is `LIQUIDATION` or `ADL` |

Live stream, one socket for every address:

```json
{"type":"subscribe","channel":"userFills","id":"0x...","accountIndex":0,"snapshot":true,"nFills":20}
```

Unsubscribe repeats `channel`, `id`, and `accountIndex`. Frames are `subscribed` (snapshot) or `channel_data` (one new fill). Both put rows in `contents.fills`. `contents.isSnapshot` is true on the snapshot. `id` is the lowercase address. `accountIndex` is on every frame, including `0`.

`snapshot: false` skips history. `nFills` defaults to 500 and maxes at 500. Account channels are public to anyone who knows the address.

Socket caps per IP: 50 connections, 100 subscriptions per connection, 1000 subscriptions total, 24h connection lifetime. The bot reconnects and backfills with `from=<last createdAt>`.

## Market data for a later activity feed

Public. Pass the ticker (`BTC-USD`), not only the numeric id, on book and trade routes.

| Call | Use |
| --- | --- |
| `GET /v1/markets` | All markets. Filter `?marketId=1`. `tickSize`, `stepSize`, `markPrice`, `oraclePrice`, margin fractions, `status` (`ONLINE`/`OFFLINE`). |
| `GET /v1/markets/feeSchedules` | Maker/taker ppm by tier |
| `GET /v1/mids` | Mid by ticker |
| `GET /v1/prices` | Mark and oracle by market id |
| `GET /v1/bbo/BTC-USD` | Best bid and ask |
| `GET /v1/l2OrderBook/BTC-USD?nLevels=20` | Book. `nLevels` 1-100 |
| `GET /v1/trades?market=BTC-USD&limit=20` | Public prints |
| `GET /v1/candles?market=BTC-USD&timeframe=1m&to=<us>&countback=1` | OHLCV. Timeframes: `1m 3m 5m 15m 30m 1h 2h 4h 8h 12h 1d 3d 1w`. `to` is required microseconds. |
| `GET /v1/fundingRates?market=BTC-USD` | Historical funding |
| `GET /v1/feetiers` | Exchange fee tiers |
| `GET /v1/leaderboard?sortBy=volume&window=24h` | `sortBy` is `volume`, `pnl`, or `fees`. `window` is `24h`, `30d`, or `all`. |

WebSocket channels on the same `/v1/ws` socket: `l2Orderbook`, `l2OrderbookUpdates`, `trades`, `bbo`, `markets`, `oraclePrices`, `candles`, `predictedFunding`. Subscribe with `{"type":"subscribe","channel":"trades","id":"BTC-USD"}`. `markets` has no `id`.

## Account reads

Same public `?address=` rule. Optional `accountIndex` (default 0).

| Call | Use |
| --- | --- |
| `GET /v1/account` | Equity, free collateral, positions. `404` until the first deposit. |
| `GET /v1/positions` | Open perp positions |
| `GET /v1/openOrders` | Resting orders |
| `GET /v1/orders` | Order history. `from`/`to` are microseconds. |
| `GET /v1/order?address=&orderId=` | One order. Needs the owning address. |
| `GET /v1/funding` | Funding payments |
| `GET /v1/portfolio` | Equity and pnl series |
| `GET /v1/account/stats` | Volume and fees |
| `GET /v1/leverages` | Leverage and cross/isolated per market |
| `GET /v1/accountTransferUpdates` | Deposits, withdrawals, transfers |
| `GET /v1/rateLimit` | Order and cancel pool left for that subaccount |
| `GET /v1/spotPositions` | Spot collateral balances |
| `GET /v1/spotFills` | Lending seizure and loan-settle fills, not order-book trades |
| `GET /v1/interest` | Borrow interest |
| `GET /v1/spotAssets` | Collateral assets accepted for lending |
| `GET /v1/lendingAttributes` | Borrow caps and rates |

Matching websocket channels: `orders`, `positions`, `account`, `funding`, `spotPositions`, `spotFills`, `accountTransferUpdates`.

## Placing orders

Not used by this bot. Mutating calls need an Ed25519 key registered with `POST /v1/createApiKey` (EIP-712, domain name `Arcus API Key`, version `1`, chain id `4663`). The server stores the public key only.

Headers on writes: `X-API-Key` (64 hex public key), `X-Timestamp` (Unix nanoseconds, within 30s of server time), `X-Signature` (128 hex).

`placeOrder`, `cancelOrder`, and `modifyOrder` sign the canonical payload itself. `ct` inside it equals `X-Timestamp`. Address `ad` is lowercase.

```
place  {"ad":"0x…","ai":0,"ct":N,"g":N,"m":1,"op":1,"p":N,"q":N,"r":0,"s":0,"t":0,"v":1}
cancel {"ad":"0x…","ai":0,"ct":N,"id":"…","m":1,"op":2,"v":1}
modify {"ad":"0x…","ai":0,"ct":N,"g":N,"id":"…","m":1,"op":3,"p":N,"q":N,"r":0,"s":0,"t":0,"v":1}
```

`p` is price divided by `tickSize`. `q` is size divided by `stepSize`. Both must divide evenly. `s` is `0` buy, `1` sell. `t` is `0` GTT, `1` FOK, `2` IOC, `3` ALO. `g` is `goodTilTime` in nanoseconds. The REST body sends `goodTilTime` in microseconds, at least one month ahead, including IOC and FOK. Body `price` and `quantity` stay decimal strings.

`POST /v1/placeOrder` usually returns `202` with `status: ACK`. The lifecycle arrives on the `orders` channel: `OPEN`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REJECTED`. Market orders must be `IOC` and the `price` must sit within 10% of the mark. Take-profit and stop-loss go through `POST /v1/batchPlaceOrders`, not single `placeOrder`.

Other writes: `POST /v1/cancelOrder`, `/v1/batchCancelOrders`, `/v1/cancelAllOrders`, `/v1/modifyOrder`, `/v1/batchModifyOrders`, `/v1/setLeverage`, `/v1/adjustIsolatedMargin`, `/v1/scheduleCancel` (dead-man cancel, 5s to 5min lead), `/v1/withdraw`, `/v1/transfer`, `/v1/settleLoan`.

Order writes are free on the IP weight bucket. Each subaccount starts with an order pool of 20,000 and a cancel pool of 40,000. `GET /v1/rateLimit` shows what is left.

IP budget is 1,500 weight per minute. A `429` body `{"error":"rate limited"}` is the IP bucket. `reason: account_empty` or `account_partial` is the subaccount pool.

## Spot

Stock-token spot is a different host from the perp API. Quote, sign, submit:

| | |
| --- | --- |
| Mainnet router | `https://router.spot.arcus.xyz` |
| Chain | Robinhood Chain `4663` |

`GET /v1/tokens`, `GET /v1/price`, `GET /v1/quote`, `POST /v1/submit`, `GET /v1/status`. Partner access needs a key from Arcus. Perp `userFills` does not include these trades.

## Doc pages

- https://docs.arcus.xyz/api-reference/introduction
- https://docs.arcus.xyz/api-reference/authentication
- https://docs.arcus.xyz/api-reference/websocket
- https://docs.arcus.xyz/api-reference/rate-limits
- https://docs.arcus.xyz/api-reference/public/get-fills
- https://docs.arcus.xyz/api-reference/account/userfills
- https://docs.arcus.xyz/api-reference/exchange/place-order
- https://docs.arcus.xyz/guides/rest-trading
- https://docs.arcus.xyz/concepts/spot-router
