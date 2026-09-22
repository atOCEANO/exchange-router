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
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## Migration

Three hops, newest first. The wire schema has not changed across any of them: `schema_version` has been 3 throughout, so code reading raw response bodies or stream messages is unaffected every time. What changes is the Python surface.

<br>

## Client 5.x to 3.0.0

**The version number appears to go backwards.** The service and the client used to be numbered separately, 2.5.7 and 5.1.1. There is one number now and it continues the service's line, which is the one the tags and releases have always used. A 5.1.1 install and a 3.0.0 install are different packages, not two versions of one.

**The package name changed.** What was `pip install exchange-router-client`, imported as `exchange_router_client`, is now `pip install exchange-router`, imported as `exchange_router`. The base install carries the Python API and local mode; `exchange-router[server]` adds FastAPI and uvicorn for running the service.

**Nothing you call has changed its name, signature or return type.** Every read method, the market handle, `Row`, `BatchResult`, `with_provenance`, `funding_paid`, `per_hour_view` and the error tree are identical. A search and replace on the import line is the whole migration for code that already worked.

**Construction is the one break, and it cannot happen silently.** `ExchangeRouterClient()` still exists, still defaults to localhost, and still works; it emits a `DeprecationWarning` naming its replacement. New code uses one of two constructors, and both require the exchange scope:

```python
from exchange_router import Router

r = Router.local(exchanges=["binance"])
r = Router.service("http://localhost:8040", exchanges=["binance"])
```

Bare `Router(...)` raises rather than guessing. Mode is never inferred from a missing URL, so configuration-driven code branches explicitly:

```python
r = Router.service(url, exchanges=E) if url else Router.local(exchanges=E)
```

**What is new.** `Router.local` is the library: the adapters run in your own program, with no container to deploy. `.mode` and `.schema_version` report what you built. `.warm()` blocks until the declared scope is ready, so the cost lands where you choose. `SchemaMismatch` joins the error tree and is raised on the first call when an SDK and a service disagree on the wire contract, instead of failing later in a way that looks like bad data. `get_exchange_overview` and `get_exchange_status` expose two routes the SDK previously did not reach.

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
