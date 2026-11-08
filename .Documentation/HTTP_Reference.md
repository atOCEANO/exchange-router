<h1>OCEΛNO <small><code>exchange-router</code></small></h1>


<div style="padding-top: 0px;">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.123.0-05998b.svg?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</div>

<sub>
  <a href="../README.md">Introduction</a> &nbsp;•&nbsp;
  <a href="Python_API.md">Python API</a> &nbsp;•&nbsp;
  <b>HTTP Reference</b> &nbsp;•&nbsp;
  <a href="Exchange_Notes.md">Exchange Notes</a> &nbsp;•&nbsp;
  <a href="Architecture.md">Architecture</a> &nbsp;•&nbsp;
  <a href="Decisions.md">Decisions</a> &nbsp;•&nbsp;
  <a href="Migration.md">Migration</a> &nbsp;•&nbsp;
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## HTTP Reference

This is the wire format of the service, which is what `Router.service` speaks and what any non-Python client would use. It is not the API most readers want: [Python API](Python_API.md) is, and it covers both modes. Read this page when you are writing a client in another language, debugging a response by hand, or checking exactly what a field means on the wire.

The same shapes come back in local mode, because the local backend serves the same records; it just never puts them on a socket. The schema is pinned by `schema_version`, which is `4` and moves only on a breaking change; every REST answer also carries it in a `Schema-Version` header, and the service publishes every route's answer and its error answers in `/openapi.json`.

The service exposes two interfaces on the same port. REST is request/response; WebSocket is real-time streaming.

*   **REST Base URI:** `http://localhost:8040`
*   **WebSocket Base URI:** `ws://localhost:8040/ws/{exchange}/{market_type}`

Worked response examples for every route, with the discrete vs continuous funding variants shown side-by-side, are in the [Response Shapes](#response-shapes) section below.


### Path Variables

*   `{exchange}`: Exchange identifier (e.g., `binance`, `bybit`).
*   `{market_type}`: Market category (`spot`, `linear`, `inverse`).
*   `{symbol}`: Trading pair (e.g., `BTCUSDT`).

<br>
<br>


## REST

The REST interface covers everything that is request/response based: service discovery, capability maps, historical data pulls, and point-in-time snapshots. Every endpoint returns a normalized JSON payload matching one of the schemas documented in Response Shapes below, regardless of which upstream exchange served the request.

Every quantitative record (Trade, Candle, OpenInterest, etc.) carries nested value objects with their unit and their notional in the quote currency; every record carries a `quote` field at the row level so it is interpretable in isolation. Where venues differ in what a value means, the record says which case it is in a kind, such as the funding model, the source of a price or the clock that stamped a snapshot, so application code branches on the kind rather than on the exchange.

<br>

### Endpoints

**Discovery**

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Service introspection: version, schema_version, and every registered exchange with its supported market types. | None |
| `GET` | `/status` | Service health check (thin slice of `/`). | None |
| `GET` | `/version` | Service version and schema_version. | None |
| `GET` | `/exchanges` | Lists all active adapters. | None |
| `GET` | `/{exchange}` | Exchange overview: each market type with its capabilities and `symbol_count`, the number of markets that trade, `null` when the market list could not be read. | None |
| `GET` | `/{exchange}/capabilities` | Supported REST routes and WebSocket channels for an adapter. | None |
| `GET` | `/{exchange}/market_types` | Market types available on the exchange. | None |
| `GET` | `/{exchange}/{market_type}/markets` | Lite list of the markets in one state, with `status`, `base`, `quote`, the `qty` unit and contract size, and `funding.kind`. `status` is `trading` by default, or `halted`, `pre_trading`, `delisted` or `all`. On `linear` and `inverse`, only perpetuals are returned. Served from the in-memory adapter cache (refreshed at most once per 24h): no upstream calls once the cache is warm, and the first request to arrive on a cold cache fills it. | `status` |
| `GET` | `/{exchange}/{market_type}/markets/{symbol}` | Full `SymbolInfo` for one symbol: its state, the price and quantity grids, order limits, contract size, funding convention, and when the record was read. | None |

**Pricing**

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/{exchange}/{market_type}/ticker/{symbol}` | 24h rolling window price and volume stats. | None |
| `GET` | `/{exchange}/{market_type}/book_ticker/{symbol}` | Best bid/ask price and quantity. | None |

**Trades**

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/{exchange}/{market_type}/trades/{symbol}` | Recent public trades. | `limit` |
| `GET` | `/{exchange}/{market_type}/agg_trades/{symbol}` | Aggregated trade history. | `end`, `limit` |

**Orderbook**

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/{exchange}/{market_type}/orderbook/{symbol}` | Current L2 orderbook snapshot. | `depth` |

**Historical Data**

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/{exchange}/{market_type}/candles/{symbol}` | OHLCV candles. | `interval`, `end`, `limit` |

**Futures** &nbsp;•&nbsp; *linear and inverse market types only*

| Method | Route | Description | Params |
| :--- | :--- | :--- | :--- |
| `GET` | `/{exchange}/{market_type}/mark_price/{symbol}` | Mark price, index price, and current funding view. | None |
| `GET` | `/{exchange}/{market_type}/liquidations/{symbol}` | Recent forced liquidation events. | `end`, `limit` |
| `GET` | `/{exchange}/{market_type}/funding_rate/{symbol}` | Historical funding rates. | `end`, `limit` |
| `GET` | `/{exchange}/{market_type}/open_interest/{symbol}` | Open interest history. On `linear` markets the route joins matching candles to price the notional; on `inverse` it uses `contract_size` directly. Where the exchange keeps no history, one live reading. | `interval`, `end`, `limit` |
| `GET` | `/{exchange}/{market_type}/long_short_ratio/{symbol}` | Long/short account distribution. | `interval`, `end`, `limit` |
| `GET` | `/{exchange}/{market_type}/margin_tiers/{symbol}` | Margin tiers: the leverage cap and margin rates a position gets at each size. | None |

A route answers a query key it does not take with a `400` that names the keys it does take, so `start` and `period`, the names `end` and `interval` had before 3.3.0, are refused by name. A live reading takes neither `interval` nor `end`.

<br>

### Pagination Semantics

Every endpoint that accepts an `end` query parameter (candles, agg_trades, funding_rate, open_interest, liquidations, long_short_ratio) treats it as an **inclusive backward-walking upper bound**:

* `?end=X&limit=N` returns up to N records with `timestamp <= X`, sorted ascending. X is the newest record in the response when present in the dataset.
* Omit `end` to get the most recent N records ending at "now".
* The response is always sorted ascending (oldest first), regardless of whether `end` was set.

The pagination loop for "load older" is therefore: pass the oldest timestamp you already have, minus one, as the new `end`, request the next page, prepend to your view. Passing the oldest timestamp itself returns that row again.

<div align="center">
  <img src="imgs/204650.png" alt="Backward-walking pagination" width="90%" />
  <p style="margin: 0;"><i>Each call's anchor is the prior call's oldest record minus one; the response is always sorted oldest-first regardless of which call</i></p>
</div>

A request walks back at most 100 of the exchange's pages. A `limit` beyond what 100 pages hold is refused with a `400` that names the most the route serves, and so is a read that reaches the hundredth page short of its `limit`. A page that fails fails the whole request; the router never returns the pages it got as if they were all. Where the exchange holds nothing older, the response is simply shorter than `limit`.

<br>

### Interpretation Fields

Every quantitative record carries one or more kinds that change how a value should be read. Branching on these is how application code stays exchange-agnostic.

| Field | Where it appears | Value | What it means |
| :--- | :--- | :--- | :--- |
| `status` | SymbolInfo / the market list | `"trading"` | The market matches orders now. |
|  |  | `"halted"` | Listed but not matching: paused, in a break, or taking cancels only. |
|  |  | `"pre_trading"` | Listed, not yet open. |
|  |  | `"delisted"` | Delisted and still served by the exchange. |
| `price.kind` | SymbolInfo | `"tick"` | Prices sit on a grid of `price.tick`. |
|  |  | `"significant_figures"` | Prices keep `price.figures` significant figures and at most `price.decimals` decimals; there is no tick. |
| `unit` | qty / volume / open_interest / SymbolInfo.qty | `"base"` | `native` is in the base coin (BTC for BTCUSDT, etc.) |
|  |  | `"contract"` | `native` is a contract count; the same block carries `contract_size` for converting to the quote |
| `notional_basis.method` | volume / open_interest | `"row_price"` | `notional = native * price`, at the row's own price, which the basis names with its `ts`: the ticker's price, or a candle's close stamped at its open. |
|  |  | `"candle_close"` | `notional` came from a candle join. The basis carries the close and the candle's stamp used. Both are null if the join missed, in which case `notional` is null too while `native` is always populated. |
|  |  | `"mark"` | `notional` is priced at the mark the exchange sent with a live reading, named with its `ts`. |
|  |  | `"contract_size"` | `notional = native * contract_size`, exact and price-independent. Used on inverse contracts where each contract represents a fixed quote-currency notional; the basis carries no price. |
| `price_source` | Ticker | `"last_trade"` | `price` is the last trade. |
|  |  | `"mid"` | `price` is the middle of the best bid and ask. |
|  |  | `"mark"` | `price` is the mark price. |
| `time_source` | snapshots / OpenInterest / SymbolInfo | `"venue"` | `timestamp` is the exchange's own time for the record. |
|  |  | `"router"` | `timestamp` is the router's clock when it read an exchange that sends no time. |
| `funding.kind` | MarkPrice.funding / FundingRate.funding / SymbolInfo.funding | `"discrete"` | Settles at fixed cycles. `per_cycle * notional` is charged at the settlement `valid_until` names. |
|  |  | `"continuous"` | Accrues smoothly between samples. Compute paid via `per_cycle * notional * (overlap_ms / cycle_ms)` over your position window. |
| `funding.valid_until.kind` | MarkPrice.funding | `"settlement"` | `ts` is the settlement at which this rate is charged. |
|  |  | `"estimate"` | `ts` is when the rate is next expected to change; no charge happens there. |
| `account_scope` | LongShortRatio | `"top_traders"` | Only top-trader accounts per the upstream's classification. |
|  |  | `"all_accounts"` | Every account at the venue. |
|  |  | `"opaque"` | Upstream exposes only the ratio; `long_account` and `short_account` will be null. |
| `up_to_unit` | MarginTiers | `"quote"` | Each tier's `up_to` is a position value in the quote asset. |
|  |  | `"base"` | `up_to` is an amount of the base coin. |
|  |  | `"contract"` | `up_to` is a contract count. |
| `side` | Trade / AggTrade | `"buy"` / `"sell"` | Taker (aggressor) side. Universal across venues. |
|  | Liquidation | `"buy"` / `"sell"` | The liquidation order's book side, the opposite of the liquidated position's side: a long being liquidated produces `"sell"`. |

A kind is an open string: `/openapi.json` lists its known values in the field's description and declares no enum, so a value added later reaches a client as one it has not seen rather than as a refused answer. A client that meets one leaves the block it qualifies uninterpreted, and the SDK keeps the value and warns. `side`, the error titles and the market types are fixed sets and are published as enums.

The SDK helpers (`per_hour_view`, `funding_paid`) already branch on these fields, so application code does not have to. For which value each venue uses on which route, see [Exchange Notes](Exchange_Notes.md).

<br>

### Response Shapes

All REST responses are normalized to the same schema regardless of the upstream exchange. Timestamps are Unix milliseconds. Prices are floats in the row's `quote` currency. Quantitative fields (qty, volume, open_interest) are **nested value objects** that carry the native upstream value, its unit, and a `notional` in the row's `quote`, so on a EUR or BTC pair it is in EUR or BTC; sum `notional` across rows only where their `quote` matches. A notional that needs a price names it in `notional_basis`. A value the exchange did not send is `null`, and a nullable field is always present. WebSocket channels emit the same shapes, noted inline.

**Service root** &nbsp;•&nbsp; `GET /`
```json
{
  "service": "exchange-router-service",
  "version": "x.y.z",
  "schema_version": 4,
  "exchanges": [
    {"name": "binance", "market_types": ["spot", "linear", "inverse"]},
    {"name": "bybit",   "market_types": ["spot", "linear", "inverse"]}
  ]
}
```

**Exchange overview** &nbsp;•&nbsp; `GET /{exchange}`
```json
{
  "exchange": "binance",
  "market_types": [
    {
      "market_type": "linear",
      "symbol_count": 287,
      "capabilities": { "...": "per-route booleans and limits" }
    }
  ]
}
```

`symbol_count` counts the markets that trade, and is `null` when the router could not read the market list.

**Markets list** &nbsp;•&nbsp; `GET /{exchange}/{market_type}/markets`
```json
{
  "exchange": "binance",
  "market_type": "linear",
  "count": 287,
  "markets": [
    {
      "symbol": "BTCUSDT",
      "status": "trading",
      "base": "BTC",
      "quote": "USDT",
      "qty": {"unit": "base", "contract_size": null},
      "funding": {"kind": "discrete"}
    }
  ]
}
```

The lite entry carries just enough metadata to enumerate and filter symbols without a per-symbol round trip. Use `/markets/{symbol}` for the full `SymbolInfo`. The list holds the markets that trade; `?status=halted`, `pre_trading`, `delisted` or `all` lists the others.

**Symbol Info** &nbsp;•&nbsp; `GET /{exchange}/{market_type}/markets/{symbol}`
```json
{
  "symbol": "BTCUSD",
  "market_type": "inverse",
  "native_symbol": "BTCUSD_PERP",
  "status": "trading",
  "base": "BTC",
  "quote": "USD",
  "price": {"kind": "tick", "tick": 0.1, "decimals": 1},
  "qty": {
    "unit": "contract",
    "contract_size": 100.0,
    "step": 1.0,
    "decimals": 0,
    "min": 1.0,
    "max": 1000000.0
  },
  "notional": {"min": null},
  "funding": {"kind": "discrete"},
  "timestamp": 1794180344479,
  "time_source": "router"
}
```

Where the exchange states no tick, as Hyperliquid keeps five significant figures, the price block says so:

```json
"price": {"kind": "significant_figures", "figures": 5, "decimals": 1}
```

`symbol` is the routing-facing trading pair used across all router endpoints. `native_symbol` is the raw exchange symbol (e.g. `BTCUSD_PERP`, `PF_XBTUSD`) for cross-referencing back to the upstream API. `qty.unit` is `"base"` on spot/linear and `"contract"` on inverse; on inverse, `qty.contract_size` carries the quote-asset notional per contract (commonly `100` or `1`, depending on the venue). `funding` is `null` on spot, `{"kind": "discrete"}` on discrete-funding futures, and `{"kind": "continuous"}` on continuous-funding futures. Per-venue specifics live in [Exchange Notes](Exchange_Notes.md).

The `price` and `qty` blocks are the grid an order has to sit on, as the exchange states it: `price.tick` in `quote`, and `qty.step` in `qty.unit`, with the limits beside them and the smallest order value in `notional.min`. `decimals` is the number of decimal places the step implies, or on a significant-figures price the most a price may carry; check an order against the step, not the decimals, since a count cannot express a step of 10 or more. A limit or step the exchange does not state is `null`. Each exchange's sources are in [Exchange Notes](Exchange_Notes.md#tick-and-step).

`status` is the liveness signal: a market the exchange lists in any state answers here, with the state it is in and, in `timestamp`, when the router read its record. The data routes serve such a market for as long as its exchange lists it, and answer a symbol the exchange does not list at all with a `400` titled `Unknown Symbol` that names the markets route.

**Ticker** &nbsp;•&nbsp; `GET /ticker/{symbol}` &nbsp;•&nbsp; WS `ticker`
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "price": 75561.3,
  "price_source": "last_trade",
  "open_24h": 75751.0,
  "high_24h": 76168.8,
  "low_24h": 73333.0,
  "volume_24h": {
    "native": 85159.802,
    "unit": "base",
    "contract_size": null,
    "notional": 6434785346.8626,
    "notional_basis": {"method": "row_price", "price": 75561.3, "ts": 1794180340543}
  },
  "price_change_percent": -0.25,
  "timestamp": 1794180340543,
  "time_source": "venue"
}
```

`price_source` says what `price` is: the last trade on most venues, the mid on Hyperliquid, whose asset context carries no last trade. A market with no last trade answers `price` `null`, with a `null` notional, and a market whose 24-hour volume is zero answers its four 24-hour prices `null`. A market that does not trade and for which the exchange publishes no 24-hour statistics at all, as Binance does for a contract being settled, answers every price and `volume_24h` `null`, stamped by the router. On inverse markets `volume_24h.unit` is `"contract"`, `contract_size` is populated, and `notional_basis.method` is `"contract_size"` (exact conversion via the fixed notional per contract).

**Book Ticker** &nbsp;•&nbsp; `GET /book_ticker/{symbol}` &nbsp;•&nbsp; WS `book_ticker`
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "bid_price": 75560.3,
  "bid_qty": {"unit": "base", "contract_size": null, "native": 4.651, "notional": 351430.9553},
  "ask_price": 75560.4,
  "ask_qty": {"unit": "base", "contract_size": null, "native": 5.952, "notional": 449735.5008},
  "timestamp": 1794180360249,
  "time_source": "venue"
}
```

A side no one quotes answers its price and its size `null`.

**Orderbook** &nbsp;•&nbsp; `GET /orderbook/{symbol}` &nbsp;•&nbsp; WS `orderbook`
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "qty": {"unit": "base", "contract_size": null},
  "bids": [[75569.9, 18.332], [75569.8, 0.289]],
  "asks": [[75570.0, 2.788], [75570.1, 0.17]],
  "timestamp": 1794180361546,
  "time_source": "venue"
}
```

Per-level qty stays as a flat `[price, qty]` pair, and the book says once, in `qty`, what every size counts. Doubling depth-200 books just to embed a per-level notional is a poor cost/benefit trade; consumers compute it locally, as `price * qty` on a `"base"` book and as `qty * qty.contract_size` on a `"contract"` book. A side with no orders is an empty list.

**Trade** &nbsp;•&nbsp; `GET /trades/{symbol}` (list) &nbsp;•&nbsp; WS `trades`
```json
{
  "id": "8246962784",
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "price": 75576.9,
  "qty": {"unit": "base", "contract_size": null, "native": 0.001, "notional": 75.5769},
  "side": "sell",
  "timestamp": 1794180362324
}
```

A trade's `qty` extends the book's `qty` block with the amount and its notional. On inverse markets `qty.unit` is `"contract"`, `contract_size` is populated, and `qty.notional = native * contract_size` (price-independent). Worked example: with `contract_size=100`, a 5-contract trade is exactly `qty.notional = 500` regardless of price. With `contract_size=1`, `qty.native == qty.notional` for the same reason. A trade, liquidation, candle or funding row always carries the exchange's own time; a row sent without one is refused, or dropped from a stream.

**Aggregated Trade** &nbsp;•&nbsp; `GET /agg_trades/{symbol}` (list) &nbsp;•&nbsp; WS `agg_trades`
```json
{
  "agg_id": "3512589552",
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "price": 75577.0,
  "qty": {"unit": "base", "contract_size": null, "native": 0.012, "notional": 906.924},
  "first_trade_id": "8246962789",
  "last_trade_id": "8246962789",
  "side": "buy",
  "timestamp": 1794180363071
}
```

**Candle** &nbsp;•&nbsp; `GET /candles/{symbol}` (list)
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "interval": "1h",
  "timestamp": 1794175200000,
  "closed": true,
  "open": 74097.4,
  "high": 74735.3,
  "low": 73988.5,
  "close": 74438.9,
  "volume": {
    "native": 17157.358,
    "unit": "base",
    "contract_size": null,
    "notional": 1277174856.4262,
    "notional_basis": {"method": "row_price", "price": 74438.9, "ts": 1794175200000}
  }
}
```

`closed` is `false` on the bar that has not ended yet, which is only ever the newest. On linear/spot, `volume.notional = native * close` (close-as-VWAP-proxy, approximate), and the basis names the close and the bar's own stamp. On inverse, `volume.notional = native * contract_size` (exact). The `notional_basis.method` field tells you which.

A candle is stamped at the open of its bucket, while an open interest or long/short row is stamped at its reading. To pair a reading with the candle that ends at it, match the reading's `timestamp` to the candle's `timestamp` plus the interval, as the open interest join does; matching the two timestamps directly pairs each reading with the next candle.

**Mark Price** &nbsp;•&nbsp; `GET /mark_price/{symbol}` &nbsp;•&nbsp; WS `mark_price` &nbsp;•&nbsp; *linear/inverse only*

Discrete-funding variant:
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "mark_price": 75579.03050225,
  "index_price": 75593.42565217,
  "funding": {
    "kind": "discrete",
    "per_cycle": 5.093e-05,
    "cycle_ms": 28800000,
    "valid_until": {"kind": "settlement", "ts": 1794182400000}
  },
  "timestamp": 1794180364000,
  "time_source": "venue"
}
```

Continuous-funding variant:
```json
{
  "symbol": "XBTUSD",
  "market_type": "linear",
  "quote": "USD",
  "mark_price": 75515.8332416742,
  "index_price": 75509.48,
  "funding": {
    "kind": "continuous",
    "per_cycle": -6.6149937373268215e-06,
    "cycle_ms": 3600000,
    "valid_until": {"kind": "estimate", "ts": 1794183965816}
  },
  "timestamp": 1794180365816,
  "time_source": "venue"
}
```

`funding.kind` is the discriminator. On `discrete`, `per_cycle` is the estimated rate that will be charged at the settlement `valid_until` names. On `continuous`, `per_cycle` is the instantaneous per-cycle-equivalent accrual sampled at `timestamp`; partial holds pay proportionally, and `valid_until` is an `estimate` of when the rate next changes, with no charge there. The SDK's `funding_paid()` helper handles both branches correctly.

**Funding Rate** &nbsp;•&nbsp; `GET /funding_rate/{symbol}` (list)

Discrete:
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "funding": {
    "kind": "discrete",
    "per_cycle": 3.42e-05,
    "cycle_ms": 28800000
  },
  "timestamp": 1794153600000
}
```

Continuous:
```json
{
  "symbol": "XBTUSD",
  "market_type": "linear",
  "quote": "USD",
  "funding": {
    "kind": "continuous",
    "per_cycle": -6.715066666667e-06,
    "cycle_ms": 3600000
  },
  "timestamp": 1794178800000
}
```

Discrete rows are settlement events; the rate was charged at `timestamp`, and `cycle_ms` is the gap to the settlement before it. Continuous rows are sample observations; no charge happened at `timestamp`, just an observation of the instantaneous rate.

**Open Interest** &nbsp;•&nbsp; `GET /open_interest/{symbol}` (list)

Linear (notional from the joined candle close):
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "interval": "1h",
  "open_interest": {
    "native": 94663.943,
    "unit": "base",
    "contract_size": null,
    "notional": 7046679786.5827,
    "notional_basis": {"method": "candle_close", "price": 74438.9, "ts": 1794178800000}
  },
  "timestamp": 1794178800000,
  "time_source": "venue"
}
```

Inverse (notional from the fixed contract size):
```json
{
  "symbol": "BTCUSD",
  "market_type": "inverse",
  "quote": "USD",
  "interval": "1h",
  "open_interest": {
    "native": 15895054.0,
    "unit": "contract",
    "contract_size": 100.0,
    "notional": 1589505400.0,
    "notional_basis": {"method": "contract_size", "price": null, "ts": null}
  },
  "timestamp": 1794178800000,
  "time_source": "venue"
}
```

A live reading, where the exchange keeps no history:
```json
{
  "symbol": "BTCUSDC",
  "market_type": "linear",
  "quote": "USDC",
  "interval": null,
  "open_interest": {
    "native": 41974.1082,
    "unit": "base",
    "contract_size": null,
    "notional": 3172570994.1888003,
    "notional_basis": {"method": "mark", "price": 75584.0, "ts": 1794180371555}
  },
  "timestamp": 1794180371555,
  "time_source": "router"
}
```

On linear markets, the route handler fetches matching candles after the OI rows arrive (sequential, not parallel) and joins them by timestamp to price each row: `method: "candle_close"`, with the joined close in `price` and its candle's stamp in `ts`, and `notional = native * price`. If the candle read itself fails, the request fails with it. Where the exchange has no candle of that interval, the rows pass through with `notional` left `null`. If the read returns fewer than two candles, the join is skipped for the whole response with no log line, since the handler needs a second candle to derive the period offset. If the fetch succeeds but a given OI row has no matching candle, the row passes through with `notional` `null` and the basis's `price` and `ts` both `null`. The raw `native` is always populated. A history row carries the exchange's time; a live reading has no `interval`, takes neither `interval` nor `end`, is stamped by the router when it was read, and is priced at the mark the exchange sent with it.

**Liquidation** &nbsp;•&nbsp; `GET /liquidations/{symbol}` (list) &nbsp;•&nbsp; WS `liquidations`
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "side": "buy",
  "price": 75622.3,
  "qty": {"unit": "base", "contract_size": null, "native": 0.0051, "notional": 385.67373},
  "timestamp": 1794180181137
}
```

**Long/Short Ratio** &nbsp;•&nbsp; `GET /long_short_ratio/{symbol}` (list)
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "interval": "5m",
  "ratio": 2.888,
  "long_account": 0.7428,
  "short_account": 0.2572,
  "account_scope": "all_accounts",
  "timestamp": 1794180000000
}
```

No `quote` field; this metric is dimensionless. `account_scope` carries the upstream's aggregation level: `"top_traders"`, `"all_accounts"`, or `"opaque"` when no breakdown is exposed. Per-exchange specifics live in [Exchange Notes](Exchange_Notes.md). Cross-exchange comparisons require matching scope.

**Margin Tiers** &nbsp;•&nbsp; `GET /margin_tiers/{symbol}` &nbsp;•&nbsp; *linear/inverse only*
```json
{
  "symbol": "BTCUSDT",
  "market_type": "linear",
  "quote": "USDT",
  "up_to_unit": "quote",
  "tiers": [
    {
      "up_to": 300000.0,
      "max_leverage": 150.0,
      "maintenance_margin_rate": 0.0033,
      "initial_margin_rate": 0.0066,
      "maintenance_deduction": null
    },
    {
      "up_to": 2000000.0,
      "max_leverage": 100.0,
      "maintenance_margin_rate": 0.005,
      "initial_margin_rate": 0.01,
      "maintenance_deduction": 510.0
    }
  ],
  "timestamp": 1793808120000
}
```

The first two of Bybit `BTCUSDT`'s 35 tiers. A tier covers positions up to its `up_to`, read through `up_to_unit`, and an open last tier has `up_to` null. The rates are fractions of a position's value, and `maintenance_deduction` comes off the position's value times `maintenance_margin_rate`, in that value's unit: the quote asset on a linear market, the coin on an inverse one. A `contract` count converts through the `contract_size` that `/markets/{symbol}` gives. A value the exchange does not serve is null, as Bybit's first deduction and every Hyperliquid rate are. `timestamp` is when the router read the table from the exchange; a table is kept for 24 hours, so a cached answer says how old it is. A listed symbol whose exchange serves no table answers `"tiers": []`. Which exchanges serve tiers, and where each reads them, is in [Exchange Notes](Exchange_Notes.md#margin-tiers).

<br>

### HTTP Status Codes

| Code | Status | Meaning |
| :--- | :--- | :--- |
| **200** | Success | Request succeeded and the payload was normalized. |
| **400** | Bad Request | The request is wrong: a parameter out of range or of the wrong type, a query key the route does not take, a market type the exchange does not offer, a symbol it does not list, or an argument the exchange itself refused. |
| **404** | Not Found | Exchange not registered, or no route at that path. |
| **500** | Internal Error | Unhandled server-side error. |
| **501** | Not Implemented | Route not supported by the target adapter on this market type. |
| **502** | Bad Upstream Response | Upstream answered but the body could not be normalized into the schema, or a record arrived without its own value. |
| **503** | Service Unavailable | Upstream rate-limit or ban window active, an outage the exchange reported, or the retry budget was exhausted. Carries a `Retry-After` header (seconds) when the adapter knows the wait. Retry later; the request itself was valid. |

<br>

Every error answer, from every route and from a stream before it closes, is one body: an `error` title from a fixed list and a `detail` sentence that names what was wrong and, where there is one, the fix.

```json
{"error": "Unknown Symbol", "detail": "NOPEUSDT is not listed on binance linear; /binance/linear/markets lists the symbols"}
```

| Status | `error` |
| :--- | :--- |
| **400** | `"Invalid Request"`, or `"Unknown Symbol"` for a symbol the exchange does not list |
| **404** | `"Not Found"` |
| **500** | `"Internal Server Error"` |
| **501** | `"Not Implemented"` |
| **502** | `"Bad Upstream Response"` |
| **503** | `"Upstream Unavailable"` |

The seven titles are the whole list, and `/openapi.json` publishes them as an enum on `ErrorBody`, so a client can switch on `error`. A path or query parameter that fails validation answers `400` `Invalid Request` with one sentence naming the parameter, never a list of checks.

The router never masks upstream error detail. If the underlying exchange returns a specific message, it is passed through in `detail`.

**Common causes by code:**

* **400** `Unknown Symbol` means the exchange does not list the symbol on this market type, answered after the router has read the exchange's list again, at most once a minute. `Invalid Request` means the request itself is wrong: a query key the route does not take (`period: the candles route takes interval, not period`), a market type that does not exist or the exchange does not offer, a `limit` or `depth` below 1, a `limit` beyond what 100 pages hold, an `interval` the venue does not declare (check `GET /{exchange}/capabilities`), an `interval` or `end` sent to a live reading, or an argument the exchange answered with its own invalid-argument code.
* **404** means the exchange name in the path is not registered: a typo, or an adapter that failed to load at startup (check the router's stdout for `Failed to load adapter`). A path no route serves answers `404` too, with `no route GET /path` in `detail`; on `margin_tiers` that comes from a service older than 3.2.0, which has no such route, and the SDK raises `NotSupported` naming the service's version.
* **500** means an adapter bug or an unexpected error escaped the request loop. A reproducible 500 is a bug report.
* **501** means the route is not supported on this exchange and market, per the capability map: for example `funding_rate` or `mark_price` on spot, `liquidations` on KuCoin or Kraken, `long_short_ratio` on Bybit spot or any spot market, `margin_tiers` on any spot market and on Binance, Kraken and KuCoin.
* **502** means the upstream answered but the body could not be normalized into the schema, usually a shape drift on the venue side, or a record in it lacked its own value, such as a trade without a price. The `detail` carries the validation error or names the record.
* **503** means the upstream is throttling or has banned the IP and the wait exceeds the adapter's fail-fast threshold (30s on Bybit and KuCoin, 60s on OKX), the exchange reported itself busy or down inside a `200` answer, as Bybit, OKX, KuCoin and Kraken do, or the retry budget was exhausted on any adapter. The request was valid; retry after the `Retry-After` window. Binance and Kraken do not fail fast on an active cooldown; they sleep and retry, and surface `503` only once the retry budget is exhausted.

<br>
<br>

## WebSocket

The WebSocket interface covers everything REST does not. It carries real-time streams from the exchange pushed through without polling. The two interfaces share a port and a schema, so a `ticker` WebSocket message looks identical to a `GET /ticker/{symbol}` response body, and you can pick whichever fits the workload.

Connect to `ws://localhost:8040/ws/{exchange}/{market_type}` and send a JSON subscription naming the channel, the symbol and the schema the client reads:

```json
{"channel": "trades", "symbol": "BTCUSDT", "schema_version": 4}
```

The router subscribes at the exchange and waits up to 30 seconds for its answer. When the exchange takes the subscription, the router sends a `subscribed` frame and then the data; a refusal or no answer sends the error body and closes the connection (see [Close Codes](#close-codes)). A client joining a stream the router already carries gets its `subscribed` frame before any data, at once while the exchange holds the subscription and otherwise when the exchange takes it.

```json
{"subscribed": {"channel": "trades", "symbol": "BTCUSDT", "schema_version": 4, "ts": 1794180362324}}
```

When the exchange connection drops, the router sends `lost` and keeps the client's connection open while it reconnects; when the exchange takes the subscription again, `subscribed` follows, and data resumes after it. Silence after `subscribed` is a quiet market; silence after `lost` is the exchange away.

```json
{"lost": {"channel": "trades", "symbol": "BTCUSDT", "ts": 1794180401102}}
```

A control frame is an object with the single key `subscribed` or `lost`, so a client tells it from data by that key. Control frames reach each client in order, before the data that follows them.

<br>

### Protocol Rules

* **One subscription per connection.** A connection is bound to a single `(channel, symbol)` tuple. To subscribe to more than one, open additional connections. The internal `StreamManager` still shares a single upstream exchange connection between any clients that pick the same tuple, so this does not create redundant upstream connections.
* **No unsubscribe message.** Close the connection to unsubscribe. The server tears down resources immediately.
* **No client heartbeat required.** Exchange-specific ping/pong handling is abstracted inside the adapter. The server does not close idle connections on its own.
* **A dead exchange connection is replaced.** The router pings every exchange; when one stops answering, the router sends `lost`, reconnects and subscribes again while the client's connection stays open, and sends `subscribed` once the exchange takes it back. A quiet market keeps its connection, since its exchange still answers the pings, and a stream with nothing to report simply sends nothing.
* **The subscription names its schema.** A subscription whose `schema_version` is missing or not `4` is refused with the error body, so a client built for another schema learns it at once instead of misreading the frames.
* **Stream payloads match REST shapes.** A `ticker` subscription yields the same JSON object as `GET /ticker/{symbol}`, including the nested value objects and the `quote` field. See the response shapes above.
* **Availability is not uniform.** Not every channel is available on every exchange or market type. Check `GET /{exchange}/capabilities` before subscribing.

<br>

### Channels

| Channel | Description | Payload |
| :--- | :--- | :--- |
| `ticker` | 24h rolling price and volume stats. | `{"channel": "ticker", "symbol": "BTCUSDT", "schema_version": 4}` |
| `book_ticker` | Best bid/ask updates. | `{"channel": "book_ticker", "symbol": "BTCUSDT", "schema_version": 4}` |
| `trades` | Individual public trade executions. | `{"channel": "trades", "symbol": "BTCUSDT", "schema_version": 4}` |
| `agg_trades` | Aggregated trade events. | `{"channel": "agg_trades", "symbol": "BTCUSDT", "schema_version": 4}` |
| `orderbook` | L2 orderbook depth updates. | `{"channel": "orderbook", "symbol": "BTCUSDT", "schema_version": 4}` |
| `mark_price` | Mark price and funding view updates. | `{"channel": "mark_price", "symbol": "BTCUSDT", "schema_version": 4}` |
| `liquidations` | Real-time liquidation events. | `{"channel": "liquidations", "symbol": "BTCUSDT", "schema_version": 4}` |

<br>

### Close Codes

The router accepts every connection and refuses a subscription by sending the error body, the same one a REST route gives for the same fault, and then closing with a code that says whether to fix the request or retry it.

| Code | Meaning |
| :--- | :--- |
| **1003** | The subscription is wrong or not served, with the body's status a `400` or a `501`: an exchange that is not registered, a market type it does not offer, no subscription within 10 seconds of connecting, a `schema_version` other than `4`, a `channel` or `symbol` missing, a channel the router does not know, a channel the capability map does not stream on this market, a symbol the exchange does not list (`Unknown Symbol`), or a subscription the exchange refused, whose reason the body carries. Fix the subscription before sending it again. |
| **1011** | The exchange failed, with the body's status a `502`, a `503` or a `500`: it gave no answer to the subscription within 30 seconds, it failed while the router read its listing to check the symbol, or it ended the stream. Reconnect and subscribe again. |

The close's reason repeats the body's `detail`, cut to the 123 bytes a close frame holds; the body carries it whole.

A client that does not take a frame within 5 seconds is closed with `1011` and the reason `Send timeout`, without a body.

<br>
<br>

## Examples

For full parameter details see the endpoint tables above and [Parameter defaults](#parameter-defaults).

REST, with `curl`:

```bash
curl http://localhost:8040/
curl http://localhost:8040/exchanges
curl http://localhost:8040/binance/capabilities
curl http://localhost:8040/binance/linear/markets
curl http://localhost:8040/binance/inverse/markets/BTCUSD
curl http://localhost:8040/binance/spot/ticker/BTCUSDT
curl "http://localhost:8040/bybit/linear/candles/ETHUSDT?interval=1h&limit=500"
```

The block above hits, in order: service introspection, the active-adapter list, Binance's capability map (check this before building clients), the lite markets list (served from cache once it is warm), the full `SymbolInfo` for one symbol, a spot ticker, and 500 1h candles for a Bybit linear pair.

WebSocket, with `wscat`:

```bash
wscat -c ws://localhost:8040/ws/binance/spot
> {"channel": "trades", "symbol": "BTCUSDT", "schema_version": 4}
```

The `subscribed` frame arrives once Binance takes the subscription, and trade events follow it.

<br>
<br>

## Parameter defaults

Default values applied when the caller omits the query parameter. The router's one maximum is the 100-page walk of a paginated route; every other cap is per-exchange and lives in the `/capabilities` map.

| Parameter | Min | Max | Default |
| :--- | :--- | :--- | :--- |
| `depth` (orderbook) | 1 | * | 20 |
| `limit` (trades) | 1 | * | 100 |
| `limit` (agg_trades) | 1 | * | 500 |
| `limit` (candles) | 1 | * | 100 |
| `limit` (open_interest) | 1 | * | 30 |
| `limit` (funding_rate) | 1 | * | 100 |
| `limit` (liquidations) | 1 | * | 100 |
| `limit` (long_short_ratio) | 1 | * | 30 |
| `interval` (candles) | - | - | 1h |
| `interval` (open_interest) | - | - | 1h |
| `interval` (long_short_ratio) | - | - | 5m |

`*` Determined by the capabilities map for each exchange and route. Paginated routes (`candles`, `agg_trades`, `funding_rate`, `open_interest`, `liquidations`, `long_short_ratio`) walk back through history bounded by upstream retention and by the 100-page walk in [Pagination Semantics](#pagination-semantics). Non-paginated routes (`trades`, `orderbook`) clamp to the per-exchange `max_limit` (`max_depth` for orderbook) declared in capabilities.

`interval` carries no numeric range. It is checked against the route's `intervals` list in the capability map when the adapter declares one, and an undeclared value returns `400` before the adapter is called. A route whose capability block serves REST and declares `intervals` as `null` is a live reading, which takes no `interval` and no `end`.

Per-venue semantic quirks (what `funding.valid_until` names, ticker timestamp lag on Binance, trade-id formats, 1000-prefix tokens, long/short breakdown availability) live in [Exchange Notes](Exchange_Notes.md).
