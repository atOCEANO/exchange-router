<h1>OCEΛNO <small><code>exchange-router</code></small></h1>


<div style="padding-top: 0px;">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.123.0-05998b.svg?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</div>

<sub>
  <a href="../README.md">Introduction</a> &nbsp;•&nbsp;
  <a href="Python_API.md">Python API</a> &nbsp;•&nbsp;
  <a href="HTTP_Reference.md">HTTP Reference</a> &nbsp;•&nbsp;
  <a href="Exchange_Notes.md">Exchange Notes</a> &nbsp;•&nbsp;
  <a href="Architecture.md">Architecture</a> &nbsp;•&nbsp;
  <a href="Decisions.md">Decisions</a> &nbsp;•&nbsp;
  <b>Migration</b> &nbsp;•&nbsp;
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## Migration

Seven hops, newest first. 4.0.0 moves `schema_version` to 4: it renames and restructures what the wire and the SDK carry, so code written against 3.x changes as the first hop lists. Before it, `schema_version` was 3 throughout: no field was renamed, removed or retyped, so code written against an older 3.x release keeps parsing what a newer one sends. 3.3.0 corrects values and answers, 3.2.0 adds a route, and 3.1.0 two fields and five corrected values; the hops before them change the Python surface.

<br>

## 3.3.x to 4.0.0

**Upgrade the SDK and the service together.** A 3.x SDK stops at its first call against a 4.0.0 service with `SchemaMismatch`, and the 4.0.0 SDK against a 3.x service, each naming which side to upgrade. A raw stream client is refused until its subscription names `"schema_version": 4`, and every REST answer says `Schema-Version: 4`. The decisions behind the new shapes are [0026, 0027 and 0028](Decisions.md).

**Names and blocks on the wire.**

| Where | 3.3.x | 4.0.0 |
| :--- | :--- | :--- |
| Every quantity block (`qty`, `volume`, `volume_24h`, `open_interest`, `bid_qty`, `ask_qty`) | `usd`, `usd_basis` with `method`, `close`, `close_ts` | `notional`, `notional_basis` with `method`, `price`, `ts`; `method` `close` is `row_price` |
| Symbol info | `base_asset`, `quote_asset`, `price_precision`, `quantity_precision`, `tick_size`, `qty_step`, `min_qty`, `max_qty`, `min_notional`, `qty_unit`, `contract_size` | `base`, `quote`, a `price` block (`kind`, `tick` or `figures`, `decimals`), a `qty` block (`unit`, `contract_size`, `step`, `decimals`, `min`, `max`) and `notional.min`, with `market_type`, `status`, `timestamp` and `time_source` added |
| Market list entries | `base_asset`, `quote_asset`, `qty_unit`, `contract_size` | `status`, `base`, `quote`, `qty` with `unit` and `contract_size` |
| Order book | `qty_unit` after the levels | `qty` with `unit` and `contract_size` before them |
| Mark price | `funding.valid_until_ts` | `funding.valid_until` with `kind`, `settlement` or `estimate`, and `ts` |
| Funding history | `rate` | `funding` |
| Capability map | `markets` | `market_types` |
| Exchange overview and service root | `status`; overview entries keyed `name` | no `status`; entries keyed `market_type` |
| `/{exchange}/status` | an adapter health string | removed |
| Query keys `start` and `period` | accepted beside `end` and `interval` | refused with a `400` that names the key the route takes |

The ticker gains `price_source`, the snapshots and open interest gain `time_source`, every candle gains `closed`, and the market list takes `?status=`. A kind is an open string, so a client meets a value it does not know as a value, not as a refused answer.

**Null where nothing happened.**

| Case | 3.3.x | 4.0.0 |
| :--- | :--- | :--- |
| Ticker with no last trade | `price` `0.0` | `price` `null`, and its notional `null` |
| Ticker with no volume in 24 hours | the open, high, low and change each exchange sent, `0` on some | `null` |
| Book side no one quotes | price and size `0.0` | `null` |
| Hyperliquid's live open interest | `interval` as asked, `1h` by default, and `usd` `null` | `interval` `null`, priced at the mark Hyperliquid sends with it, `time_source` `"router"`; `interval` and `end` refused |
| Symbol info of a market that does not trade | absent from `/markets/{symbol}` | served, with its `status` |
| Ticker of a market that does not trade and has no statistics, as a contract Binance is settling | `502` | every price and `volume_24h` `null`, `time_source` `"router"` |

**Errors.** Every error answer is one body, `{"error", "detail"}`, whose `error` is one of seven titles, and its status says who is at fault:

* A path or query parameter that fails validation answers `400` `Invalid Request` with one sentence, where it answered `422` with a list. A method a path does not serve answers `404`, where it answered `405`.
* A symbol the exchange does not list answers `400` titled `Unknown Symbol`; in Python it is still `BadRequest`, with `.error` saying which.
* An answer the router cannot read answers `502` whatever error reading it raised, where it answered `400` or `500`, and an exchange error code other than an invalid argument answers `502`, where it answered `400`. An exchange's invalid-argument codes still answer `400`.
* A stream that refuses or ends a subscription sends the error body first, and closes with `1003` when the subscription is at fault and `1011` when the exchange is. An unlisted symbol closes with `1003`, where it closed with `1008`, and an unregistered exchange or a market type the exchange does not offer is refused with the body after the connection opens, where the handshake failed with `403`.
* A subscription the exchange refuses raises `BadRequest` in Python, where it raised `NotSupported`, and a market type the exchange does not offer raises `BadRequest` on a stream in both modes.

**Streams.** The router sends `subscribed` when the exchange takes a subscription and `lost` when the exchange connection drops, then `subscribed` again when it takes the topic back; a raw client tells them from data by their single key. The SDK yields data only and warns once per gap with its bounds, its own reconnects included.

**Python names.**

| 3.3.x | 4.0.0 |
| :--- | :--- |
| `volume_usd`, `qty_usd`, `open_interest_usd`, `volume_24h_usd`, `bid_qty_usd`, `ask_qty_usd` | `volume_notional`, `qty_notional`, `open_interest_notional`, `volume_24h_notional`, `bid_qty_notional`, `ask_qty_notional` |
| `df.attrs["usd_basis"]` | `df.attrs["notional_basis"]` |
| funding frame columns `rate`, `cycle_ms` | `funding_per_cycle`, `funding_cycle_ms` |
| open interest attr `oi_unit` | removed; `open_interest_unit` |
| symbol info keys `base_asset`, `quote_asset`, `price_precision`, `quantity_precision`, `tick_size`, `qty_step`, `min_qty`, `max_qty`, `min_notional`, `contract_size` | `base`, `quote`, `price_kind`, `price_tick`, `price_figures`, `price_decimals`, `qty_unit`, `qty_contract_size`, `qty_step`, `qty_decimals`, `qty_min`, `qty_max`, `notional_min` |
| `start=` and `period=` on series methods and `*_many` | removed; `end=` and `interval=` |
| `get_markets(...)` returning `{"markets": [...]}` | `get_markets(...)` returning the list |
| `get_exchange_status(exchange)` | removed |

Candle frames lead with a `closed` column, ticker and book ticker rows carry `time_source` and the ticker `price_source`, mark price rows `funding_valid_until_kind`, the order book's `attrs` carry `qty_contract_size` and `time_source`, and open interest's `attrs` carry `time_source`. Every row and frame warns on a kind the SDK does not know and keeps the value.

<br>
<br>

## 3.2.x to 3.3.0

**Nothing is renamed or removed; new names sit beside the old ones.** `end` names the newest bound of every paged route and method, and `interval` the bucket of open interest and long/short; `start` and `period` are still accepted. Open interest frames carry `open_interest_unit` beside `oi_unit`, `with_provenance` adds `market_type`, and a `BatchResult` is a read-only mapping, so `dict(result)` works. Every REST answer carries a `Schema-Version` header and every error body an `error` key. The SDK still sends `start` and `period` on the wire, so it reads a 3.2.x service as before.

**Values that were wrong are corrected.**

| Exchange and route | Field | 3.2.x | 3.3.0 |
| :--- | :--- | :--- | :--- |
| Bybit liquidations | `side` | the side of the position closed | the side of the liquidation order, as on Binance and OKX |
| OKX mark price | `funding.valid_until_ts` | the settlement after the one that charges `per_cycle` | the settlement that charges it |
| OKX candles and open interest, 6h and longer | `timestamp` | bars opening at 16:00 UTC | bars on the UTC grid |
| Hyperliquid open interest | `timestamp`, `usd` | the last period boundary, priced at its close | when read, `usd` null |
| Hyperliquid ticker | `high_24h`, `low_24h` | widened by the book's mid | traded hourly bars only, `0.0` with none |
| Funding history, every exchange | `rate.cycle_ms` | the symbol's current cycle on every row | the cycle each row settled under |
| Binance and OKX mark price, when the cycle lookup fails | `funding` | an 8-hour cycle assumed | `null` until the cycle is read |
| KuCoin and Kraken records, Bybit liquidations | price, size, rate | `0.0` where the exchange left it out | refused: `502` on REST, a skipped frame on a stream |
| Kraken and KuCoin inverse, Bybit | `contract_size`, precisions | `1.0`, or Bybit's fallback precisions, where the exchange left them out | the instrument stays out of the market list |

**Some answers change.**

* A symbol the exchange does not list raises `BadRequest` naming `/markets` on every route and stream, where it got one of three answers. A market in any state the exchange lists, halted or cancel-only included, is served with its real `quote`; `/markets` still shows only what trades.
* Bybit's USDC perpetuals are named by base and quote, `BTCUSDC` where 3.2.x said `BTCPERP`, which is still accepted. KuCoin's USDC-margined contracts lose their `M`, `XBTUSDC`, and Kraken spot also resolves `BTCUSD`, `XXBTZUSD` and `BTC/USD` to `XBTUSD`.
* An empty book side reads price and size `0.0` on every exchange; Kraken, KuCoin and Hyperliquid answered `400`.
* A read that fails partway fails as a whole, where it returned the pages it had; a `limit` beyond 100 pages is refused with a `400`. An outage an exchange reports inside a `200` raises `UpstreamUnavailable`, where it raised `BadRequest`.
* On KuCoin spot and Hyperliquid a candle `limit` counts bars, so a quiet market answers its newest bars, however old.
* A stream waits for the exchange's answer to its subscription: a refusal raises `NotSupported` with the exchange's reason, and no answer within 30 seconds is retried. A connection that goes silent is replaced.
* An empty frame has a full frame's columns, dtypes, UTC `DatetimeIndex` and `attrs` keys, where it had a `RangeIndex` and object columns. `funding_paid` warns when a frame has lost its `funding_kind`, and a ticker or book ticker quoted outside the dollar family warns as a frame does. `fetch_many` refuses a keyword its route does not take before fetching anything.

<br>
<br>

## 3.1.x to 3.2.0

**One route is added, and nothing is renamed or removed.** `GET /{exchange}/{market_type}/margin_tiers/{symbol}` serves an exchange's margin tiers, read in Python with `get_margin_tiers(...)` or `m.margin_tiers()` as a `DataFrame`, and every market's capability block gains `margin_tiers`. Bybit, OKX and Hyperliquid serve it on their perpetuals; spot markets and Binance, Kraken and KuCoin answer `501`.

**An older service has no such route.** A 3.1.x or older service answers the path with a bare `404`. The 3.2.0 SDK, finding no `margin_tiers` block in that service's capabilities, raises `NotSupported` naming the service's version before it asks. Every other method reads an older service as before.

<br>
<br>

## 3.0.x to 3.1.0

**Two fields are added, and nothing is renamed or removed.** `SymbolInfo` gains `tick_size` and `qty_step`, the grid an order has to sit on, after `funding` on the wire and before `funding_kind` on the `Row`. A `Row` read from a 3.0.x service has both as `None`.

**Five values were wrong and are corrected.** Each moves on these instruments only:

| Exchange and market | Field | 3.0.x | 3.1.0 |
| :--- | :--- | :--- | :--- |
| Kraken futures | `quantity_precision` | `8` on every perpetual | the instrument's `contractValueTradePrecision`, at least `0` (`4` on `PF_XBTUSD`) |
| Kraken futures | `price_precision` | `0` where the tick is finer than ten decimals | the tick's decimals (`11` on `PF_MOGUSD`) |
| Bybit spot | `quantity_precision` | `3` on every pair | the decimals of `basePrecision` (`6` on `BTCUSDT`) |
| Bybit spot | `min_notional` | `null` on every pair | `minOrderAmt` (`5` on `BTCUSDT`) |
| KuCoin futures | `price_precision` | `0` where the tick is below `0.0001` | the tick's decimals (`5` on `DOGEUSDTM`) |

Code that rounds by these precisions rounds differently on those instruments, and code that reads Bybit spot's `min_notional` now sees a minimum where it saw none.

<br>
<br>

## Client 5.x to 3.0.0

**The version number appears to go backwards.** The service and the client used to be numbered separately, 2.5.7 and 5.1.1. There is one number now and it continues the service's line, which is the one the tags and releases have always used. A 5.1.1 install and a 3.0.0 install are different packages, not two versions of one.

**The package name changed.** What was `pip install exchange-router-client`, imported as `exchange_router_client`, is now `pip install exchange-router`, imported as `exchange_router`. The base install carries the Python API and local mode; `exchange-router[server]` adds FastAPI and uvicorn for running the service.

**Nothing you call has changed its name, signature or return type.** Every read method, the market handle, `Row`, `BatchResult`, `with_provenance`, `funding_paid`, `per_hour_view` and the error tree are identical. A search and replace on the import line is the whole migration for code that already worked, with one exception: `get_capabilities` used to answer a failed fetch with an empty dict and now raises, so code that tested the result for emptiness to detect an unreachable service should catch `RouterError` instead.

**Construction is the one break, and it cannot happen silently.** `ExchangeRouterClient()` and `AsyncExchangeRouterClient()` still exist, still default to localhost, and still work; each emits a `DeprecationWarning` naming its replacement. New code uses one of two constructors, and both require the exchange scope:

```python
from exchange_router import Router

r = Router.local(exchanges=["binance"])
r = Router.service("http://localhost:8040", exchanges=["binance"])
```

Bare `Router(...)` raises rather than guessing. Mode is never inferred from a missing URL, so configuration-driven code branches explicitly:

```python
r = Router.service(url, exchanges=E) if url else Router.local(exchanges=E)
```

**What is new.** `Router.local` is the library: the adapters run in your own program, with no container to deploy. `.mode` and `.schema_version` report what you built, and `.degraded` reports whether an opt-in `fallback="local"` has taken over. `.warm()` blocks until the declared scope is ready, so the cost lands where you choose. `SchemaMismatch` joins the error tree and is raised on the first call when an SDK and a service disagree on the wire contract, instead of failing later in a way that looks like bad data. `get_exchange_overview` and `get_exchange_status` expose two routes the SDK previously did not reach.

Before reaching for local mode, read [Which mode to use](../README.md#which-mode-to-use): each local process carries its own rate-limit budget, and the exchange sees the sum.

<br>
<br>

## Client 4.x to 5.x

The wire schema is unchanged. Three client-side changes can break 4.x code:

* **The DataFrame index is timezone-aware UTC now.** Comparing it against a naive `Timestamp` raises; localize your bound with `tz="UTC"`, or call `.tz_localize(None)` on the index.
* **`fetch_multi_candles` was removed.** Use `candles_many`, which returns a `BatchResult`.
* **Python 3.10 or newer is required.**

<br>
<br>

## Client 3.x to 4.x

The wire schema is unchanged, so any code reading the raw response bodies (or stream messages) is unaffected. The client return shapes changed:

* **Snapshots are now a flat `Row`, not a nested dict.** `t["volume_24h"]["native"]` becomes `t.volume_24h` (or `t["volume_24h"]`); the nested object is on `t.raw`. Funding on `get_mark_price` is flat: `mp.funding_per_cycle`, `mp.funding_kind`, plus the derived `mp.funding_per_hour`.
* **`get_orderbook` returns one DataFrame, not `(bids, asks)`.** Split with `ob[ob.side == "bid"]` and `ob[ob.side == "ask"]`.
* **Series columns are stable.** `cycle_ms` is always a column on funding, and `long_account` / `short_account` are always columns on long/short ratio (NaN when opaque). Code that did `KeyError`-prone column access now works.
* **`df.attrs` keys are unchanged in spirit** but the conversion provenance stays in `attrs`; for per-row provenance across a `concat`, use `with_provenance`.
* **`get_symbol_info` returns a `Row`** with `funding_kind` instead of a nested `funding` block.
* **4xx errors** still raise the typed `RouterError` tree from 3.x.
