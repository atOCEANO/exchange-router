<h1>OCEΛNO <small><code>exchange-router</code></small></h1>


<div style="padding-top: 0px;">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.123.0-05998b.svg?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</div>

<sub>
  <a href="../README.md">Introduction</a> &nbsp;•&nbsp;
  <b>Python API</b> &nbsp;•&nbsp;
  <a href="HTTP_Reference.md">HTTP Reference</a> &nbsp;•&nbsp;
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

## Python API

`Router` is the whole API. It is synchronous by default: methods return their data directly, with no `await`. The sync class runs the async machinery on a private background event loop, so the same code works in a plain script and in a Jupyter cell without `asyncio.run` or top-level `await`. An `AsyncRouter` with the identical surface is available when you want concurrency.

The only decision is which constructor to call. `Router.local` is the library: the exchange adapters run inside your own program. `Router.service` translates the same calls into HTTP against a service you are running. Nothing else about your code changes; [Which mode to use](../README.md#which-mode-to-use) says when to pick each.

The return surface follows one rule:

> Anything tabular is a pandas **DataFrame** with flat, stable columns. A single quote is a flat **Row** you read with `t.price`. Batches are a **BatchResult**. Every quantity is named the same way everywhere: `x` (native), `x_notional` (its value in the quote), `x_unit` (what `x` counts).

| Kind | Returns |
| :--- | :--- |
| Time series (candles, trades, agg_trades, funding_rate, open_interest, liquidations, long_short_ratio) | `pandas.DataFrame`, datetime index, sorted oldest-first, flat stable columns |
| Point snapshot (ticker, book_ticker, mark_price, symbol_info) | `Row`, a flat `dict` with attribute access and a `.raw` wire-dict escape hatch |
| Order book | one `DataFrame` with columns `side, price, qty` |
| Margin tiers | one `DataFrame` with a plain row index, one row per tier |
| Batch (`*_many`) | `BatchResult`, a read-only mapping over the symbols that returned |
| Discovery (exchanges, market_types, capabilities, markets) | `dict` / `list` |

Upgrading from `exchange-router-client`, or from an older client major, is covered in [Migration](Migration.md).

<br>
<br>

## Installation

```bash
pip install "git+https://github.com/atOCEANO/exchange-router.git"
```

That is everything `Router.local` and `Router.service` need. To run the service yourself, add the extra that carries FastAPI and uvicorn:

```bash
pip install "exchange-router[server] @ git+https://github.com/atOCEANO/exchange-router.git"
```

For local development, `pip install -e ".[server,test]"` from a checkout. Requires Python 3.10+.

<br>
<br>

## Construction

Two constructors, one per mode. Both require the exchange scope, and bare `Router(...)` raises rather than guessing.

```text
Router.local(
    exchanges,                  # required: a list of names, or "all"
    *,
    verbose = True,
)

Router.service(
    url,                        # required
    exchanges,                  # required: a list of names, or "all"
    *,
    fallback    = None,         # "local" to degrade to local adapters, one way, off by default
    timeout     = 30,
    max_retries = 3,
    verbose     = True,
)
```

Nothing is inferred. In particular the mode is never chosen from a missing URL, because an unset config variable arriving as `None` would silently hand you a private per-process rate budget when you asked for the shared one. Config-driven code branches explicitly:

```python
r = Router.service(url, exchanges=E) if url else Router.local(exchanges=E)
```

`fallback="local"` is the one exception, and it is opt-in for the same reason. When the service cannot be reached the router switches to local adapters, warns you that it has, and sets `r.degraded`. It is one way: nothing probes for the service coming back, because a router that silently moves between a shared rate budget and a private one is the thing the paragraph above refuses to do at construction. Call `r.warm()` after a switch to warm the adapters that are now serving.

Whatever scope you name is warmed in the background and nothing else is, so a slow start always has a cause you can see. The scope is not a fence: a call to an exchange you did not declare still works, and warms lazily.

```python
r.mode              # "local" | "service"
r.scope             # the exchange names you declared
r.degraded          # True once fallback="local" has taken over
r.schema_version    # 4, the wire contract this SDK speaks
r.warm()            # block until the declared scope is ready
r.warm("kraken")    # warm one, declared or not
```

`exchanges="all"` is answered by the registry in local mode and by the service in service mode, so a service-mode `r.scope` reads empty until the router has spoken to the service once. `r.warm()` forces that.

`warm()` is the blocking form of something already happening. Use it to keep the cost out of your first measurement. In service mode it runs the schema handshake and the capability fetch instead, so it means the same thing in both modes.

Both constructors also accept `backend=`, which replaces the one they would have built. It exists so the test suite can drive the app in process and stand in a fake service without reaching into a private attribute. Passing your own works; a `Backend` has to implement `fetch` and `stream`, the rest have defaults, and none of it is covered by the schema guarantee.

<br>
<br>

## Quick Start

No `await`. This runs identically in a script and in a notebook.

```python
from exchange_router import Router

with Router.local(exchanges=["binance"]) as client:
    df = client.get_candles("binance", "spot", "BTCUSDT", interval="1h", limit=100)
    print(df.tail())
```

Against a running service, one line changes:

```python
with Router.service("http://localhost:8040", exchanges=["binance"]) as client:
    df = client.get_candles("binance", "spot", "BTCUSDT", interval="1h", limit=100)
```

The router holds persistent connections and, in local mode, live adapters. Release it when done. The `with` block above guarantees cleanup; outside one, call `client.close()`. Closing is final: a call on a closed router raises rather than waiting, and closing twice is harmless. In local mode it shuts down every adapter in the process, not only the ones you declared, and empties the registry, so the next `Router.local(...)` builds fresh adapters and pays for its own warm.

Keep one local router alive at a time. Every local router in the process shares the same adapters, and each runs them on a loop of its own, so re-running a notebook cell that builds one, before closing the router it built the last time, leaves two routers over one set of adapters, and calls on the second can fail with a lock or an event bound to a different event loop. Close the first, or build it in a `with` block.

The `end` parameter, where applicable, follows the [router's pagination contract](HTTP_Reference.md#pagination-semantics): pass the oldest timestamp you already have, minus one, to walk further back.

```python
oldest = int(df.index[0].timestamp() * 1000)
older  = client.get_candles("binance", "spot", "BTCUSDT", interval="1h", limit=500, end=oldest - 1)
```

<br>
<br>

## The market handle

Binding the exchange, market type, and symbol once avoids repeating them on every call.

```python
m = client.market("kraken", "linear", "XBTUSD")

candles = m.candles(interval="1h", limit=500)
funding = m.funding_rate(limit=200)
mark    = m.mark_price()
book    = m.orderbook(depth=50)

m.info()          # full SymbolInfo as a Row
m.quote           # "USD"
m.funding_kind    # "discrete" | "continuous" | None
m.exchange, m.market_type, m.symbol
```

Iterate every market in a category as handles:

```python
for m in client.markets("binance", "linear"):
    oi = m.open_interest(interval="1h", limit=30)
```

The handle forwards to the flat `client.get_*` methods, which remain available for one-off calls and for code that iterates raw symbol strings.

<br>
<br>

## Series: the DataFrame

Series methods return a plain `pandas.DataFrame`. Nothing is wrapped, so `concat`, `merge`, `resample`, `to_parquet`, and pickling all work normally. The frame has:

* a `DatetimeIndex` built from `timestamp` (Unix milliseconds, UTC, timezone-aware), sorted oldest-first, so `df.iloc[-1]` is the newest row,
* short, lowercased, **flat** columns,
* a **stable** column set: a route always returns the same columns, NaN where a value is absent (no column that appears or disappears with the data),
* per-query constants in `df.attrs`, read right after the call,
* numeric columns coerced to numbers, text columns (`side`, `id`, the trade-id fields) left as objects,
* an empty DataFrame for an empty response, never `None`, shaped like a full one: the route's columns and dtypes, an empty UTC `DatetimeIndex`, and the route's `attrs` keys set to `None`.

Columns and `df.attrs` per route:

| Route | Columns | `df.attrs` constants |
| :--- | :--- | :--- |
| candles | `closed, open, high, low, close, volume, volume_notional` | `quote, interval, volume_unit, contract_size, notional_basis` |
| trades | `price, qty, qty_notional, side, id` | `quote, qty_unit, contract_size` |
| agg_trades | `price, qty, qty_notional, side, agg_id, first_trade_id, last_trade_id` | `quote, qty_unit, contract_size` |
| funding_rate | `funding_per_cycle, funding_cycle_ms, funding_per_hour` | `quote, funding_kind` |
| open_interest | `open_interest, open_interest_notional` | `quote, interval, open_interest_unit, contract_size, notional_basis, time_source` |
| liquidations | `price, qty, qty_notional, side` | `quote, qty_unit, contract_size` |
| long_short_ratio | `ratio, long_account, short_account` | `interval, account_scope` |

`notional_basis` is the method the rows' notionals were worked out by: `row_price`, `contract_size`, `candle_close` or `mark` (see [Interpretation Fields](HTTP_Reference.md#interpretation-fields)). On open interest, `interval` is `None` and `time_source` is `"router"` for a live reading, the one row an exchange with no history sends. `closed` is `False` only on the newest candle, while its bar is still forming.

Every frame's `attrs` also carries `exchange, market_type, symbol, schema_version, warnings`. `schema_version` is the wire schema the client was built against, pinned as a constant in the client, not the number the running service reported; when the two disagree, this field speaks for the client side.

`funding_per_hour` is `funding_per_cycle` normalized to a one-hour rate, so funding compares directly across venues with different cycle lengths. `funding_cycle_ms` is always a column (it can vary mid-window); a change within the window raises a warning. On `long_short_ratio`, `long_account` and `short_account` are always columns and come back `NaN` on venues that expose only the ratio (`account_scope == "opaque"`).

```python
df = client.get_candles("binance", "spot", "BTCUSDT", interval="1h", limit=3)
```

```text
                           closed     open     high      low    close   volume  volume_notional
datetime
2026-11-08 19:00:00+00:00    True  74097.4  74735.3  73988.5  74438.9   812.34           6.05e7
2026-11-08 20:00:00+00:00    True  74438.9  75724.4  74407.2  75569.9   934.12           7.06e7
2026-11-08 21:00:00+00:00   False  75569.9  75610.0  75520.1  75561.3    41.07           3.10e6

df.attrs
{'exchange': 'binance', 'market_type': 'spot', 'symbol': 'BTCUSDT',
 'schema_version': 4, 'warnings': [], 'quote': 'USDT', 'interval': '1h',
 'volume_unit': 'base', 'contract_size': None, 'notional_basis': 'row_price'}
```

`df.attrs` holds constants for the query, read them right after the call. pandas drops `attrs` across `merge` / `groupby` / `concat`, but you rarely need them back: the comparable `*_notional` column is first-class, so cross-venue work uses it and never touches `unit`. When you do want provenance to survive a `concat`, see [with_provenance](#provenance-across-a-concat).

<br>
<br>

## Snapshots: the Row

`get_ticker`, `get_book_ticker`, `get_mark_price`, and `get_symbol_info` return a `Row`: a flat `dict` subclass with attribute access. It is a real dict, so it pickles, JSON-dumps, and drops into `pd.DataFrame([...])`. The nested value objects from the wire are flattened to `x` / `x_notional` / `x_unit`, and each block of symbol info to keys prefixed with its name. The original nested wire dict is on `.raw`.

```python
t = client.get_ticker("binance", "linear", "BTCUSDT")

t.price                 # 75561.3
t.price_source          # "last_trade"
t.volume_24h            # 85159.802       (native)
t.volume_24h_notional   # 6434785346.86
t.volume_24h_unit       # "base"
t["price"]              # key access works too; it is a dict
t.timestamp             # 1794180340543   (unix milliseconds)
t.time_source           # "venue"
t.raw                   # the original nested wire dict, untouched

rows = [client.get_ticker("binance", "linear", s) for s in symbols]
pd.DataFrame(rows)      # one row per symbol, for free
```

Mark price flattens funding and adds a per-hour figure:

```python
mp = client.get_mark_price("kraken", "linear", "XBTUSD")

mp.mark_price                  # 75515.83
mp.index_price                 # 75509.48   (or None)
mp.funding_kind                # "continuous"
mp.funding_per_cycle           # -0.0000066
mp.funding_per_hour            # -0.0000066  (derived, comparable across venues)
mp.funding_valid_until_kind    # "estimate"
```

Symbol info carries the grid an order has to sit on:

```python
info = client.get_symbol_info("binance", "linear", "BTCUSDT")

info.status        # "trading"
info.price_tick    # 0.1
info.qty_step      # 0.001
info.qty_min       # 0.001
info.notional_min  # 50.0
```

Row keys per snapshot (missing values are `None`, never absent):

| Snapshot | Keys |
| :--- | :--- |
| ticker | `symbol, market_type, quote, price, price_source, open_24h, high_24h, low_24h, volume_24h, volume_24h_notional, volume_24h_unit, price_change_percent, timestamp, time_source` |
| book_ticker | `symbol, market_type, quote, bid_price, bid_qty, bid_qty_notional, ask_price, ask_qty, ask_qty_notional, qty_unit, timestamp, time_source` |
| mark_price | `symbol, market_type, quote, mark_price, index_price, funding_kind, funding_per_cycle, funding_cycle_ms, funding_per_hour, funding_valid_until_ts, funding_valid_until_kind, timestamp, time_source` |
| symbol_info | `symbol, market_type, native_symbol, status, base, quote, price_kind, price_tick, price_figures, price_decimals, qty_unit, qty_contract_size, qty_step, qty_decimals, qty_min, qty_max, notional_min, funding_kind, timestamp, time_source` |

`price_tick` is `None` where the exchange keeps significant figures instead of a tick, as Hyperliquid does; `price_figures` says how many.

<br>
<br>

## Order book

`get_orderbook` returns one tidy `DataFrame` with columns `side, price, qty` (`side` is `"bid"` or `"ask"`), bids best-first then asks best-first. `quote`, `qty_unit`, `qty_contract_size`, `timestamp` and `time_source` are in `df.attrs`.

```python
ob = client.get_orderbook("binance", "linear", "BTCUSDT", depth=20)

bids   = ob[ob.side == "bid"]
asks   = ob[ob.side == "ask"]
spread = asks.price.min() - bids.price.max()
ob.attrs["qty_unit"]    # "base"
```

<br>
<br>

## Margin tiers

`get_margin_tiers` returns an exchange's tier table for one perpetual: a `DataFrame` with a plain row index and the columns `up_to, max_leverage, maintenance_margin_rate, initial_margin_rate, maintenance_deduction`, one row per tier in rising order. `quote`, `up_to_unit`, and `timestamp` are in `df.attrs`. `up_to_unit` says whether `up_to` is a position value in the quote asset (`"quote"`), an amount of the base coin (`"base"`) or a contract count (`"contract"`), and `timestamp` is when the router read the table from the exchange. The rates are fractions of a position's value, and `maintenance_deduction` comes off the position's value times `maintenance_margin_rate`, in that value's unit: the quote asset on a linear market, the coin on an inverse one. A `"contract"` count converts through the `contract_size` that `get_symbol_info` gives. An open last tier's `up_to` is `NaN`, and so is any value the exchange does not serve.

```python
tiers = client.get_margin_tiers("bybit", "linear", "BTCUSDT")

tiers.attrs["up_to_unit"]          # "quote"
tiers.iloc[0].up_to                # 300000.0
tiers.iloc[0].max_leverage         # 150.0
```

Spot markets, and Binance, Kraken and KuCoin, raise `NotSupported`, as does a service older than 3.2.0, which the message names by its version. A listed symbol whose exchange serves no table returns the empty frame with its columns and a warning. On a market handle the same call is `m.margin_tiers()`. Where each exchange reads its tiers is in [Exchange Notes](Exchange_Notes.md#margin-tiers).

<br>
<br>

## Provenance across a concat

`df.attrs` does not survive `pd.concat`. When you stitch frames from several venues and need per-row provenance, `with_provenance` promotes the constants to columns first:

```python
from exchange_router import with_provenance

frames = [
    with_provenance(client.get_candles("binance", "linear",  "BTCUSDT", interval="1h", limit=500)),
    with_provenance(client.get_candles("bybit",   "inverse", "BTCUSD",  interval="1h", limit=500)),
]
both = pd.concat(frames)
both.groupby("exchange")["volume_notional"].sum()   # exchange, market_type, symbol, quote, unit ride per-row
```

`market_type` rides along so the spot and perpetual frames of one symbol stay apart after the concat.

<br>
<br>

## Warnings

The SDK tells you when a result is missing data, approximate, or degraded, so you do not analyze it by accident. `verbose=True` is the default.

```python
client = Router.local(exchanges=["binance"], verbose=True)
```

Set `verbose=False` once for a quiet client, or override per call:

```python
df = client.get_open_interest("binance", "linear", "BTCUSDT", verbose=False)
```

Warnings fire only when a result deviates from the clean case you would expect, never for facts that are always true of a market type. They surface through Python's `warnings` module under the `RouterDataWarning` category, so a test can promote them to errors and a consumer can filter them. They are also attached to the result's `df.attrs["warnings"]`.

```python
df = client.get_open_interest("binance", "linear", "BTCUSDT", interval="5m", limit=30)
df.attrs["warnings"]
# ['open_interest binance/linear/BTCUSDT: 2 of 30 rows have notional=NaN (join missed; native is populated)']
```

What warns: open-interest rows with a `NaN` notional, fewer rows than requested on a paginated route (the exchange holds nothing older), a mark price with no index or no funding, an opaque long/short scope (the account columns are `NaN`), trades with null ids, a funding cycle that changed mid-window, a quote currency outside the dollar family on a frame, a ticker or a book ticker, a margin tiers table with no tiers, an empty response, a kind this version does not know on any row or frame (the value is kept as sent), a stream that lost its exchange and got it back (the warning names the gap, since messages in it may be missing), and `funding_paid` handed a frame that lost its `funding_kind`.

<br>
<br>

## Batch fetching

The `*_many` methods fetch many symbols concurrently (the sync client still runs them in parallel under the hood) and return a `BatchResult`, a read-only mapping for the common case where everything worked, with diagnostics there when you need them. Each value is a DataFrame.

```python
symbols = [m["symbol"] for m in client.get_markets("binance", "linear")]

result = client.open_interest_many("binance", "linear", symbols, interval="1h", limit=100)

for symbol, df in result.items():     # every symbol that returned data
    ...

result.ok          # {symbol: DataFrame}                 clean
result.degraded    # {symbol: (DataFrame, [warnings])}    returned with gaps
result.failed      # {symbol: exception}                  never returned
result.requested   # how many symbols were asked for
result.data()      # {symbol: DataFrame}, ok and degraded together
print(result.summary())   # one line, for a log
print(result.report())    # the summary, then every symbol that was not clean
```

```text
100 requested: 97 ok, 2 degraded, 1 failed
  degraded
    APTUSDT   open_interest binance/linear/APTUSDT: 3 of 100 rows have notional=NaN (join missed; native is populated)
    SEIUSDT   open_interest binance/linear/SEIUSDT: 11 of 100 rows have notional=NaN (join missed; native is populated)
  failed
    FOOUSDT   BadRequest: ...
```

A symbol is `degraded` when the result carries warnings (in `df.attrs["warnings"]`), `failed` when the request raised, `ok` otherwise. There is a `*_many` for every series route (`candles_many`, `trades_many`, `agg_trades_many`, `funding_rate_many`, `open_interest_many`, `liquidations_many`, `long_short_ratio_many`). Every mapping read, iteration, `len()`, `in`, `result[symbol]`, `keys()`, `items()`, `get()` and `dict(result)`, reads `data()`, so a failed symbol is simply absent rather than present as `None`.

They are one function underneath, and it is public. `fetch_many` takes the route by name and passes the route's own parameters through, so code that walks several routes over one universe needs no branch per route:

```python
routes = {"candles": {"interval": "1h"}, "funding_rate": {}, "open_interest": {"interval": "1h"}}

for route, params in routes.items():
    result = client.fetch_many(route, "binance", "linear", symbols, limit=100, **params)
    print(route, result.summary())
```

A route that is not a series route raises `BadRequest`, and so does a keyword the route does not take, before any symbol is fetched.

<br>
<br>

## Helpers for funding math

```python
from exchange_router import Router
from exchange_router.funding import funding_paid, per_hour_view

with Router.local(exchanges=["binance"]) as client:
    df = client.get_funding_rate("binance", "linear", "BTCUSDT", limit=100)

    print(per_hour_view(df.iloc[-1]))

    t_open  = int(df.index[0].value // 1_000_000)
    t_close = int(df.index[-1].value // 1_000_000)
    print(funding_paid(df, t_open, t_close, notional=1_000_000))

    mark = client.get_mark_price("kraken", "linear", "XBTUSD")
    print(per_hour_view(mark))
```

These are plain functions, not coroutines, so they are never awaited. `funding_paid` handles both discrete (settlement events) and continuous (sample integration) funding correctly. It reads the kind from the frame's `funding_kind`, which `pd.concat` drops when the frames' `attrs` differ; such a frame is counted as discrete, with a warning, which misprices continuous funding such as Kraken's. Both helpers accept every shape the client produces: the `get_funding_rate` DataFrame, a single row of it, the `get_mark_price` Row (rate read from its flat `funding_*` fields), and raw wire-format rows.

<br>
<br>

## Errors

The router raises a small typed tree, so failures are programmable without parsing message strings. Every error carries `.status` (the HTTP status, where applicable), `.error` (the title of the error body, one of the seven in the [HTTP Reference](HTTP_Reference.md#http-status-codes)) and `.detail`. **The same failure raises the same type in both modes**: local mode maps adapter faults straight into this tree instead of round-tripping them through a status code. The suite asserts that for every read path. It cannot run the stream paths end to end, because the in-process transport the suite runs against carries HTTP and not websockets; there the service's refusals and the SDK's reading of them are tested apart.

| Exception | When | Modes |
| :--- | :--- | :--- |
| `BadRequest` | `400`, including an interval the route does not declare and a symbol the exchange does not list, whose `.error` is `"Unknown Symbol"` | both |
| `NotFound` | `404`, an unknown exchange or a path no route serves | both |
| `RateLimited` | `429`, which the router never sends; it can only come from a proxy between you and the service | `service` only |
| `UpstreamUnavailable` | `503`, carries `.retry_after` | both |
| `NotSupported` | the route is not exposed on this exchange and market, caught before the request, a server `501`, or a service older than the route (`margin_tiers` before 3.2.0) | both |
| `RouterUnreachable` | transport failure, or retries exhausted | `service` only |
| `SchemaMismatch` | the SDK and the service disagree on the wire contract; carries `.sdk_schema` and `.service_schema` | `service` only |
| `RouterError` | any other status the server returns (for example `500`, or a `502` for an exchange answer the router cannot read or a record that arrived without its own value), carrying `.status` | both |

`SchemaMismatch` is raised on the first call, not at construction, because the check needs a round trip and a constructor cannot await one. It is fatal and deliberately has no compatibility range: `schema_version` only moves on a breaking wire change, so a mismatch means one side genuinely cannot read the other.

```text
SchemaMismatch: this SDK speaks schema 4, http://localhost:8040 speaks schema 3
(sdk 4.0.0, service 3.3.0); upgrade the service or pin the SDK to a schema 3 release
```

```python
from exchange_router import NotSupported, UpstreamUnavailable

try:
    df = client.get_funding_rate("binance", "spot", "BTCUSDT")
except NotSupported as e:
    ...
except UpstreamUnavailable as e:
    time.sleep(e.retry_after or 5)
```

All of these inherit from `RouterError`, so `except RouterError` catches everything.

Retries live in the transport, so the two modes spend them differently. In service mode the SDK retries `429` and transient `5xx` with jittered backoff, honoring the `Retry-After` header the router sends on `503`; if the window outlasts the retry budget it raises `UpstreamUnavailable` carrying that `retry_after` so you can wait the rest. In local mode there is no HTTP hop to retry: each adapter already backs off and retries the exchange itself, and surfaces exhaustion as `UpstreamUnavailable`, usually carrying a `retry_after` (Kraken is the one that does not). A rate limit therefore reaches you as `UpstreamUnavailable` in both modes, and so does an outage the exchange reports inside its answer; `except UpstreamUnavailable` covers every case where waiting is the answer.

Symbol validity is left to the server, which normalizes case and separators. A symbol the exchange does not list raises `BadRequest` naming the markets route, in both modes, rather than a client-side guess that could falsely reject a valid symbol.

<br>
<br>

## Asynchronous router

For real concurrency, use `AsyncRouter`. It exposes the same methods and the same handle, with `await`. The async handle carries the route methods and `await m.info()`, but not the cached `m.quote` and `m.funding_kind` properties: those are defined on the sync handle only, so on an async handle they raise `AttributeError`. Read `quote` and `funding_kind` off the awaited `info()` Row instead.

```python
import asyncio
from exchange_router import AsyncRouter

async def main():
    async with AsyncRouter.service("http://localhost:8040", exchanges=["binance"]) as client:
        df = await client.get_candles("binance", "spot", "BTCUSDT", interval="1m", limit=10_000)

        m = client.market("binance", "linear", "BTCUSDT")
        funding = await m.funding_rate(limit=200)

        results = await client.candles_many("binance", "spot", ["BTCUSDT", "ETHUSDT"], interval="1d")

asyncio.run(main())
```

The batch methods on the sync router already run their fetches concurrently, so reach for the async router only when you are driving your own event loop.

<br>
<br>

## Real-time streams

`stream` checks the schema as every read does, then yields data messages as dicts and reconnects automatically, in both modes, when the exchange gives no answer to the subscription or ends the stream, which a service answers with a `503` body before it closes, or when the transport fails. It does not retry a deliberate rejection, so a misconfigured call fails fast instead of reconnecting forever. The modes raise the same error for the same refusal: a channel the exchange does not stream raises `NotSupported`; a subscription the exchange refuses raises `BadRequest` with the exchange's reason; a symbol the exchange does not list raises `BadRequest` whose `.error` is `"Unknown Symbol"`; a market type the exchange does not offer raises `BadRequest`; and an unknown exchange raises `NotFound`.

The `subscribed` and `lost` frames the router sends are not yielded. When the exchange connection drops and comes back, or the SDK reconnects on its own, the next message is preceded by one `RouterDataWarning` naming the gap, since messages inside it may be missing.

```python
for msg in client.stream("binance", "spot", "ticker", "BTCUSDT"):
    print(msg["symbol"], msg["price"])
```

Stream messages are the raw wire dicts (the same shapes as the REST response bodies), not `Row` objects; to get the flat Row shape on a ticker, book_ticker, or mark_price message, pass it through the matching builder in `exchange_router.rows`, which is `ticker_row`, `book_ticker_row` or `mark_price_row`, for example `from exchange_router.rows import ticker_row; ticker_row(msg)`. Pass `reconnect=False` to have the iterator raise `websockets.ConnectionClosed` on a drop instead. `subscribe` is the same without reconnect. On the sync router the messages cross into your thread through a buffer of 1024; a consumer slower than the feed loses the oldest, and is told so with a `RouterDataWarning` whatever `verbose` is set to, because this is data loss rather than noise. One subscription per connection: to change channel or symbol, leave the loop and start a new one. On the async router these are `async for`.

<br>
<br>

## Symbols

The router exposes routing-facing symbols: the exchange-native symbol with any contract-type prefix or suffix stripped, so Kraken `PF_XBTUSD` is addressed as `XBTUSD` and Binance COIN-M `BTCUSD_PERP` as `BTCUSD`. One symbol can name an instrument on several market types, as `BTCUSDT` does on Binance spot and linear, and `market_type` tells them apart. Base-currency codes are never translated: Kraken stays `XBT`, not `BTC`. The SDK passes symbols through unchanged. The canonical list for any venue and market type is `client.get_markets(...)`, and each entry carries `base` and `quote`; build a per-venue map when you compare venues whose base codes differ.

<br>
<br>

## Method reference

Signatures are for the sync `Router`. `AsyncRouter` is identical with `await`, and `markets()`, `stream()`, and `subscribe()` become `async`. Everything here is available in both modes.

**Lifecycle.** `warm(exchange=None)`, `close()`, the read-only `mode`, `scope`, `degraded` and `schema_version` attributes, and `verbose`, which you can set at any time to change the router's default for every later call. The installed release is `exchange_router.__version__`, which is a different number from `schema_version`: the release moves with every fix, the schema only with a breaking wire change.

**Discovery.** `get_status()`, `get_version()`, `get_exchanges()`, `get_exchange_overview(exchange)`, `get_market_types(exchange)`, `get_capabilities(exchange)`, `get_markets(exchange, market_type, status="trading")`. `get_version()` returns a version string; the others return `dict` or `list`. `get_markets` returns the list of market entries in one state: `"trading"`, `"halted"`, `"pre_trading"`, `"delisted"` or `"all"`. `get_exchange_overview` carries per-market-type symbol counts alongside the capability block, `None` where the market list could not be read. `get_capabilities` raises if the block cannot be fetched, rather than reporting an exchange with no capabilities.

**Snapshots (return `Row`).** `get_ticker(exchange, market_type, symbol)`, `get_book_ticker(...)`, `get_mark_price(...)`, `get_symbol_info(exchange, market_type, symbol)`.

**Order book (returns a `DataFrame`).** `get_orderbook(exchange, market_type, symbol, depth=20)`.

**Margin tiers (returns a `DataFrame`).** `get_margin_tiers(exchange, market_type, symbol)`, on linear and inverse markets where the exchange serves tiers. It is not a series, so no `*_many` method or `fetch_many` route takes it.

**Series (return DataFrames).**

```python
get_candles(exchange, market_type, symbol, interval="1h", limit=100, end=None)
get_trades(exchange, market_type, symbol, limit=100)
get_agg_trades(exchange, market_type, symbol, limit=500, end=None)
get_funding_rate(exchange, market_type, symbol, limit=100, end=None)
get_open_interest(exchange, market_type, symbol, interval=None, limit=30, end=None)
get_liquidations(exchange, market_type, symbol, limit=100, end=None)
get_long_short_ratio(exchange, market_type, symbol, interval=None, limit=30, end=None)
```

`interval=None` lets the route choose, `1h` on open interest and `5m` on long/short, and it is the only value a live reading takes.

**Handles.** `market(exchange, market_type, symbol)`, `markets(exchange, market_type)`.

**Batch (return `BatchResult`).** `candles_many`, `trades_many`, `agg_trades_many`, `funding_rate_many`, `open_interest_many`, `liquidations_many`, `long_short_ratio_many`, each taking the same per-route parameters plus `max_concurrent=8`, and `fetch_many(route, exchange, market_type, symbols, verbose=None, max_concurrent=8, **params)`, the general form they are built on.

**Streams.** `stream(exchange, market_type, channel, symbol, reconnect=True)`, `subscribe(exchange, market_type, channel, symbol)`. Channels: `ticker`, `book_ticker`, `trades`, `agg_trades`, `orderbook`, `mark_price`, `liquidations`. Check `get_capabilities` to confirm a channel is supported.

**Provenance helper.** `with_provenance(df)` returns a copy with `exchange`, `market_type`, `symbol`, `quote`, and `unit` promoted to columns.

`verbose` overrides the router default for that call on every series method, on `get_symbol_info`, `get_ticker`, `get_book_ticker`, `get_mark_price`, `get_orderbook` and `get_margin_tiers`, and on every `*_many` method. On `get_ticker` and `get_book_ticker` it governs the warning for a quote outside the dollar family.

<br>
<br>

