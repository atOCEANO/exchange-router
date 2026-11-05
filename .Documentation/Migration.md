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

Four hops, newest first. `schema_version` has been 3 throughout: no field has been renamed, removed or retyped, so code written against an older release keeps parsing what a newer one sends. 3.1.0 adds two fields and corrects five values; the hops before it change the Python surface.

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
