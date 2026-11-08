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
  <a href="Migration.md">Migration</a> &nbsp;•&nbsp;
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <b>Auditor Guide</b>
</sub>

<br>
<br>
<br>
<br>

## Auditor Guide

Adapter compliance is validated via the **auditor** package at `tools/auditor/`. The runner reads `/{exchange}/capabilities` and runs only the probes that apply to the features the adapter claims to support, so an honest capabilities map is the difference between a clean test run and noise. All declared endpoints must pass before submitting a Pull Request.

Getting capabilities wrong in either direction surfaces as a failure, not a skip. Claim `True` for a feature the adapter does not implement and the route either 501s (recorded by the `error_paths` probe) or succeeds in a way that contradicts the schema (recorded by `capabilities_drift`). Claim `False` for a feature that works and `capabilities_drift` flags it: a `rest: False` route that returns 200 is a hard FAIL.

The auditor stamps the served `schema_version` field on every `results.json` and pins its expected value to the constant in [exchange_router/version.py](../exchange_router/version.py). Drift between the two fails the suite, so a wire shape change that did not move the constant surfaces immediately.

<br>
<br>

## Quick orientation

| You want to ... | Open this file |
| :--- | :--- |
| Run the suite or interpret results | this document, sections [Running the suite](#running-the-suite) and [Run output](#run-output) |
| Add a new probe | `tools/auditor/probes/<your_probe>.py` next to a similar one. Register in `probes/__init__.py::market_probes` or `exchange_probes` |
| Tune an env knob (timeouts, concurrency, freshness threshold) | `tools/auditor/config.py` |
| Change how results are aggregated or written | `tools/auditor/aggregator.py` (`Aggregator`) and `tools/auditor/output/json.py` (`write_json`) / `output/live.py` (`LiveReporter`) |
| Change the orchestration (capability walk, semaphores) | `tools/auditor/runner.py` |
| Change the CLI surface | `tools/auditor/__main__.py` |

<br>
<br>

## Layout

The CLI in `__main__.py` invokes `runner.run(...)`, which executes a fixed top-of-run sequence (`/status`, `/version`, `/exchanges`), then pre-flights `/capabilities` for every target exchange in parallel. Pre-flight emits the capabilities pass/fail result per exchange and counts the probes each will dispatch (via `applies(ctx)` against a placeholder symbol), so the live progress display knows its denominator before any probe runs. The runner then fans out to one task per exchange. Inside each exchange task it reads the exchange overview, which warns when a market list could not be read, runs the exchange-level probes, then iterates per market type, picks a real symbol via `/markets`, and runs the market-level probes filtered by `applies(ctx)`. Results feed into an `Aggregator`; `LiveReporter` updates the console as they arrive (one progress bar per exchange plus a global total) and `write_json` persists the final summary.

| File | Class / Role | Lines (approx) |
| :--- | :--- | :--- |
| `__main__.py` | CLI entry: `python -m tools.auditor [exchange ...]` | 100 |
| `config.py` | env knobs, interval map, symbol picker, theoretical-max, the clock table and the venue tables (deadlines, prices, instrument records) | 285 |
| `runner.py` | top-of-run sequence, `/capabilities` pre-flight + per-exchange probe-count, the exchange overview, semaphore gating, `asyncio.gather` | 395 |
| `aggregator.py` | `ProbeResult`, `ErrorType`, `Aggregator` | 150 |
| `output/json.py` | machine-readable run output writer | 25 |
| `output/ordering.py` | display-ordering constants for the HTML report (market / route / period / sub-probe / caps-key) | 20 |
| `output/live.py` | rich live console with one progress bar per exchange plus a global total, end-of-run failure table | 265 |
| `output/html.py` | HTML report renderer (analytics <-> sample toggle) | 465 |
| `output/_urlfmt.py` | per-result request URL synthesis, param extraction, evidence compaction, shared by the HTML and live renderers | 80 |
| `probes/__init__.py` | re-exports + `market_probes()` / `exchange_probes()` registry | 80 |
| `probes/base.py` | `Probe` ABC, `ProbeContext`, `fetch`, validators, REST throttling, the table of kinds, the time judgement, the venue reads paced by host | 305 |
| `probes/snapshot.py` | `SnapshotProbe` + ticker / book / mark check helpers, the deadline and the venue price | 210 |
| `probes/orderbook.py` | `OrderBookProbe` (multi-depth, ordering, freshness) | 130 |
| `probes/trades.py` | `TradesProbe` (multi-limit, uniqueness, ordering) | 150 |
| `probes/margin_tiers.py` | `MarginTiersProbe` (shape, rising bounds, an open tier only last, rates) | 120 |
| `probes/paginated.py` | `PaginatedProbe` (recent + 5 sub-probes covering limit checks and anchored windows, and the checks of what the rows mean) | 390 |
| `probes/websocket.py` | `WebSocketProbe` + `WS_CHANNEL_MODEL` registry, `StreamRefusalProbe` (an unknown symbol on a stream) | 325 |
| `probes/info.py` | `InfoProbe` (reads `/markets/{symbol}`, name `markets:detail`, and compares it with the venue's record) | 165 |
| `probes/markets.py` | `MarketsProbe` (reads the lite `/markets` dict shape), `HaltedMarketProbe` (one halted market on every route) | 180 |
| `probes/capabilities.py` | `CapabilitiesConsistencyProbe` (drift detection) | 160 |
| `probes/errors.py` | `ErrorPathProbe` (negative paths and their error bodies) | 65 |
| `probes/cross_route.py` | `CrossRouteConsistencyProbe` (ticker vs book vs mark) | 110 |
| `probes/symbol.py` | `SymbolResolutionProbe` (canonical spot symbol resolves) | 70 |

<br>
<br>

## The `Probe` ABC

Every probe inherits from a single ABC: `Probe` in `probes/base.py`. Each subclass owns one route or one cross-cutting check, declares whether it `applies(ctx)`, and returns `List[ProbeResult]` from `run(ctx)`. Each `ProbeResult` carries a structured `evidence: dict` (offending values, request params) plus a categorical `ErrorType`. Aggregations by failure type read directly from `ErrorType` rather than parsing free-form text.

The base class gives every probe two helpers so probes don't repeat their identity at every result construction:

- `self.result(ctx, name, started, *, status, error_type, message, evidence=None, ended=None)` builds a `ProbeResult` populated with `self.route`, `self.kind`, the context's exchange/market/symbol, and the latency derived from `started -> time.time()`. Pass `ended` explicitly when the probe wants to clock end time at a moment other than result-construction (e.g. `cross_route` runs two fetches before emitting a single result).
- `self.http_failure(ctx, name, started, status_code, data, net_err, expected="200")` builds the standard fail result for non-200 responses. Override `expected` when the probe is asserting against something other than 200 (e.g. `error_paths` expecting 404).

<br>
<br>

## What the runner validates

Probes run against every advertised route. Each probe carries the capability fields that gate it.

<br>

### Snapshot routes

`ticker`, `book_ticker`, `mark_price`. Pydantic shape and route-specific invariants: every price positive or null, the ticker's `low_24h <= price <= high_24h` where `price_source` is `last_trade` (a mid or a mark can sit outside the traded range on a quiet market), book `bid <= ask` with positive sizes, mark price positive. The per-route check helpers read the **nested value objects** (`volume_24h.native`, `bid_qty.native`, `ask_qty.native`) and dereference `funding.per_cycle` when checking mark price.

Nothing happening is not a failure: a ticker with no last trade (`price` null) and a book side no one quotes report SKIP, since there is nothing to check.

Time is judged by what the row says. A `router` stamp says nothing of the exchange and is not judged for age, but it is expected only where the exchange sends no time (`config.py::ROUTER_STAMPED`), and a router stamp anywhere else WARNs. An exchange stamp older than `SNAPSHOT_FRESHNESS_MS` WARNs on a trading market and passes on a halted one, whose frozen stamp is its answer; the probe reads the market's `status` to tell them apart.

On `mark_price` a `deadline` check reads `funding.valid_until`. A `settlement` must match the exchange's own next settlement, read straight from the exchange (`config.py::DEADLINES`), within a second; one exactly one cycle off is read again once, since a settlement can fall between the two reads. An `estimate` must lie within one cycle of now. Exchanges with no such table skip.

On `ticker` a `venue_price` check reads the exchange's own reading of the source `price_source` names (`config.py::PRICES`) just before and just after it reads the router's ticker, and fails a price that lies outside that bracket by more than `PRICE_SLACK` (0.1%), so a moving market does not fail it while a wrong field does.

<br>

### Orderbook

Probed at every declared depth in `caps.depths` that falls within `[1, 100]`, or at `[1, 20, min(max_depth, 100)]` when no discrete list is declared, so Binance's declared 500 and 1000 are never probed and Kraken's `max_depth` of 500 is probed as 100. A venue whose declared depths all exceed 100 falls back to its smallest declared depth. Each level: bids strictly descending, asks strictly ascending, top-of-book not crossed, no zero or negative price or qty, `len <= depth`. Its time is judged as a snapshot's is. Failure evidence carries the offending pair (`{"side": "bids", "idx": 5, "prev": 30001.5, "this": 30001.7}`).

<br>

### Trades

Probed at `[1, min(100, max_limit), max_limit]`. Asserts ascending timestamps (router contract), unique `id` values, every `side in {"buy","sell"}`, `len <= limit`.

<br>

### Margin tiers

Probed on every market whose `margin_tiers` block declares `rest: True`, for the market's probe symbol. Pydantic shape, then hard FAILs for an open tier before the last, an `up_to` that does not rise from tier to tier, a non-positive `max_leverage`, or a rate outside `(0, 1]`, and WARNs for a `max_leverage` that rises from one tier to the next, a maintenance rate above the initial rate, or a table with no tiers.

<br>

### Paginated routes

`agg_trades`, `candles`, `funding_rate`, `open_interest`, `liquidations`, `long_short_ratio`. Each paginated route runs an unconditional set (shape, exact-count, at-most-N) plus an anchored set (past anchor at a near offset, past anchor at a deeper offset, future anchor expected to return the newest available records); anchored probes are skipped when the route declares `paginated: False`. The sub-probes today are:

- `recent`: no `end`, big limit, validates ascending order and freshness. The count check runs against a ceiling rather than the raw ask: `config.py::theoretical_max` is the smallest of the requested limit, the periods elapsed since `CRYPTO_EPOCH_MS` (2010-01-01), and `retention_ms // period_ms`, and the PASS floor is `THEORETICAL_MAX_RATIO` (0.9) of it, so a long period never fails for returning fewer records than a big limit asked for. On a paginated route a page shorter than its limit is checked against the rows before its first: none means the exchange's history starts there and the page passes, and any means the router served a short page where the exchange holds more, a FAIL. Where that read fails, the ceiling rule stands. The freshness threshold defaults to `3 * period_ms + 30s`; per-`(exchange, market_type, period)` overrides live in `config.py::FRESHNESS_OVERRIDE_MS` for upstreams documented to publish slowly (for example, an inverse 1m feed that skips empty buckets, requiring a 600s override). A stale newest candle is checked against the route's REST trades: where the venue has not traded since that bar's bucket closed, the market is quiet and the probe passes with the newest trade in its evidence, since KuCoin and Hyperliquid send no bar for a bucket without a trade.
- `limit=1`: must return exactly 1; an empty response warns rather than fails, and the count check does not run.
- `limit=5`: must return at most 5; > 5 is a hard FAIL.
- `before=1h_ago`: last record at or before the anchor. Skipped if `paginated: False`.
- `before=24h_ago`: same check at a deeper anchor. Skipped if `paginated: False`, and additionally skipped when `period_ms > 12h` (24h does not give enough room to cover one period).
- `end=future`: `end = now + 1h`, must return the newest available records (empty is a FAIL); a record dated more than one period into the future is a LOGIC FAIL.

An empty window where emptiness is an answer, a past anchor beyond retention or a quiet liquidation feed, reports SKIP.

These checks read what the `recent` rows mean, not only their shape:

- `cycles` (`funding_rate`): a row whose gap to the previous row repeats beside it must carry that gap as its `cycle_ms`, so a history that crosses a cycle change shows each side's own cycle. Fewer than three rows skip.
- `open_bar` (`candles`): no bar but the newest may be open.
- `utc_grid` (`candles` at `config.py::GRID_INTERVALS`, 6h and longer): every bar must open on a multiple of its interval since the epoch, which catches a bar cut on a local day.
- `clock` (`open_interest`): a history row carries the exchange's clock and a live reading the router's.
- `live_stamp` (a route whose capability block declares `intervals` null, as Hyperliquid's open interest does): the reading must carry `interval` null and be stamped within five seconds of the moment it was read.

<br>

### WebSocket

Subscribes with `schema_version`, holds the connection for `WS_TEST_DURATION` (default 180s) and validates **every** data frame against `WS_CHANNEL_MODEL`. The first frame must be `subscribed`, naming the channel, the symbol and the schema asked for; a data frame before it fails. `subscribed` and `lost` frames are checked apart from data and never counted as frames. Minimum frame thresholds are per-channel (`config.py::WS_MIN_FRAMES`):

| Channel | Min frames | Rationale |
| :--- | :--- | :--- |
| `orderbook` | 10 | Very chatty |
| `ticker`, `book_ticker` | 5 | Steady cadence |
| `trades`, `agg_trades`, `mark_price` | 1 | Activity-dependent |
| `liquidations` | 0 | Rare event; absence is not a failure |

Below threshold: WARN. Zero frames with threshold > 0: FAIL with error type `EMPTY`. Zero frames with threshold = 0: PASS with the message noting the window was idle but the connection succeeded. Any malformed frame: FAIL with the offending payload preserved in evidence.

A stream the exchange dropped (`lost`) that then sends fewer frames than its threshold WARNs as the exchange away rather than failing. A `trades` or `agg_trades` stream with zero frames is checked against the route's own REST trades before it fails. When the newest trades reach back past the window's start and none falls inside it, the venue did not trade and the probe reports SKIP; a trade inside the window, or a list too short to say, keeps the FAIL.

<br>

### Capabilities drift

For every route advertised as `rest: False`, calls the route and asserts the service returns non-200 (501 preferred). For `orderbook`, requests `depth = max_depth + 1` and asserts the response either errors or clamps. Drift findings appear under their own report section and are hard FAILs.

<br>

### Cross-route consistency

WARN-only. Asserts `|ticker.price - (book.bid + book.ask)/2| / ticker.price < 0.75%`, and on linear `|mark_price - ticker.price| < 1%`. Live-market jitter never produces FAILs here.

<br>

### Symbol resolution

SPOT-only. Hits a known canonical symbol per exchange (a `BTC`-quoted pair where the venue uses modern base codes, an `XBT`-quoted pair where the venue keeps legacy codes) and asserts the response symbol matches. Implicitly validates each adapter's spot-symbol resolution path.

<br>

### Negative paths

Runs first. Unknown exchange (`404` `Not Found`), bad market type (`400` `Invalid Request`) and unknown symbol (`400` `Unknown Symbol`), each body checked for its title and a detail sentence. `StreamRefusalProbe` subscribes a spot stream to an unknown symbol and expects the `Unknown Symbol` body, then a close with code 1003.

<br>

### /markets and /markets/{symbol}

An empty market list, as on a market type where the exchange lists nothing, reports SKIP. `MarketsProbe` reads the lite-list shape (`{exchange, market_type, count, markets: [...]}`), validates per-entry that `symbol` is uppercase with no slash and no duplicates, and that each entry carries the required `status`, `base`, `quote`, `qty` and `funding` keys.

`HaltedMarketProbe` (probe name `markets:halted`) asks the list for `?status=halted`. With one listed, it reads that market's symbol info, which must say `halted` with the time the router read it, and every REST route its market type serves, each of which must answer 200. With none listed, it reports SKIP.

`InfoProbe` (probe name `markets:detail`) reads the full `SymbolInfo` from `/markets/{symbol}` and asserts `qty.min <= qty.max`, non-negative decimals and a positive `price.tick` and `qty.step` where they are set. It warns when `decimals` disagrees with its step, the check that catches a count read from the wrong field. A `venue_record` check then reads the exchange's own instrument record (`config.py::INSTRUMENTS`) and compares the tick, the step, the limits, the decimals and the contract size field by field, with OKX's and KuCoin's lots turned into the coin; a field that differs FAILs, and a record the auditor cannot read reports SKIP.

A value of a kind the auditor does not know WARNs rather than fails, on every route and in stream frames (`probes/base.py::KINDS`). The runner's `_pick_symbol_for_market` helper extracts the symbol list from the `markets` array.

<br>
<br>

## Concurrency

```text
MAX_CONCURRENT_EXCHANGES            default 5     all exchanges in parallel
MAX_CONCURRENT_REST_PER_EXCHANGE    default 4     REST probes within an exchange
MAX_CONCURRENT_WS_PER_EXCHANGE      default 32    WS probes within an exchange
MIN_REST_INTERVAL_MS                default 250   minimum spacing between REST calls to the same exchange
```

REST and WS probes for the same exchange run in parallel against a shared service (WS holds 180s windows; serializing them after REST roughly doubles wall time). Use `--parallel 1` (or set `MAX_CONCURRENT_EXCHANGES=1`) for serial debugging.

<br>

### Why the auditor throttles itself (`MIN_REST_INTERVAL_MS`)

The auditor runs hundreds of REST probes per exchange in a few minutes. Real clients of this microservice almost never produce that kind of load. `MIN_REST_INTERVAL_MS` keeps the auditor from tripping upstream rate-limit responses that would otherwise look like adapter failures in the report. This is test hygiene, not a rate limiter the microservice relies on for production safety.

The check sits inside the auditor's `fetch` helper and derives the exchange name from the endpoint path (`/<exchange>/<market_type>/...`). Default 250ms is conservative against accidental concurrent bursts when `MAX_CONCURRENT_REST_PER_EXCHANGE > 1`. Set `MIN_REST_INTERVAL_MS=1000` (or higher) for an extra-safe run at high concurrency, or `0` to disable entirely. Endpoints without an exchange prefix (`/`, `/status`, `/version`, `/exchanges`) are not throttled. WS probes are not affected. An exchange whose own budget is tighter than the default gets a wider spacing in `config.py::REST_INTERVAL_MS`, and the wider of the two applies: Hyperliquid's is 3000ms, since 250ms would ask it for about four times the 1,200 weight a minute it allows.

Production rate-limit safety lives in the adapters, not in this knob (see [Rate limit headers and proactive backoff](Adapter_Guide.md#rate-limit-headers-and-proactive-backoff) in the Adapter Guide). The two layers are independent: when both apply, the slower spacing wins.

<br>
<br>

## Run output

Every run writes a fresh folder under `tools/auditor/runs/<YYYY-MM-DD_HH-MM-SS>_<exchanges>/`. When no exchanges are passed on the CLI the suffix is `_all`; otherwise it is the requested exchange names sorted and joined with `+`. Examples: `2026-06-05_14-30-12_all/`, `2026-06-05_14-30-12_binance+bybit/`. Each folder contains two files:

- `results.json`: machine-readable, stamped with the served `schema_version`. Contains the full `ProbeResult` list plus the aggregated `summary` block:
  - `totals`: pass / warn / fail / skip counts.
  - `by_error_type`: categorical breakdown (network, schema, logic, empty, ...).
  - `by_exchange`: per-exchange totals.
  - `rest_latency_by_route`: REST round-trip latency per route (count, p50, p95, p99, max). REST only because WS probes hold the connection for the full `WS_TEST_DURATION` window, which is a configured duration rather than a service-latency signal.
  - `ws_by_channel`: per-channel WS metrics (count, frames received p50/p95/max, time-to-first-frame p50/p95). Surfaces the meaningful WS measurements (throughput and warm-up time) instead of forcing them into a latency bucket.
- `report.html`: human-friendly rendering. Each probe panel shows analytics by default; a `[analytics] [sample]` pill toggle reveals the raw sample on demand. Capability matrices and per-route URLs are clickable.

The dated subdirs under `tools/auditor/runs/` are local-only; the directory itself is tracked via a `.gitkeep` so the auditor always has a stable target. The Docker compose mount `volumes: - ./tools/auditor/runs:/app/tools/auditor/runs` means runs from inside the container land on the host filesystem. The console renders a live progress bar during the run and a failure table at the end.

<br>
<br>

## Running the suite

The auditor needs `rich`, which is not a dependency of the service and is not in its image. It has its own extra:

```bash
pip install -e ".[audit]"
```

It is a developer tool that talks to the router over HTTP, so it runs beside the service rather than inside it. Exec-ing into the service container used to work, because one requirements file served both; it does not any more, and that is deliberate ([0008](Decisions.md)).

Point at the running router (defaults to `http://localhost:8040`) and invoke:

```bash
export API_URL=http://localhost:8040
python -m tools.auditor
```

To run it in Docker, which is where verification belongs, build the test stage and give the container the service's network:

```bash
docker build --target test -t router-dev .
docker run --rm --network container:exchange-router-service \
    -e API_URL=http://127.0.0.1:8040 \
    -v "$PWD/tools/auditor/runs:/app/tools/auditor/runs" \
    router-dev python -m tools.auditor
```

Targeting a single adapter, or a subset:

```bash
python -m tools.auditor okx
python -m tools.auditor binance bybit
```

Controlling adapter parallelism via CLI (overrides `MAX_CONCURRENT_EXCHANGES`). Use `--parallel 1` for serial debugging, `-p 2` to run two adapters at a time:

```bash
python -m tools.auditor --parallel 1
python -m tools.auditor -p 2 binance bybit kraken
```

Extending the WebSocket observation window for stress runs:

```bash
WS_TEST_DURATION=300 python -m tools.auditor
```

Inside Docker, prepend `docker exec exchange-router-service` to any of the commands above to run against the live container.

<br>
<br>

## Why the suite runs locally, not in CI

The auditor hits live exchange APIs, so it only works from a host those exchanges will answer, and a GitHub Actions runner is not such a host. Hosted runners issue requests from cloud datacenter IP ranges, and exchanges routinely block those: some ban server-provider and datacenter IPs outright, and several geo-block the US regions GitHub's runners run in. A run from there surfaces as connection failures and 403s that look like adapter regressions but are really the venue refusing the runner's IP. Run the suite from an environment with unblocked exchange access (a local machine, or a box in a region the venues serve), not from CI.

The same applies to Google Colab and other hosted notebooks: they run on cloud IPs (Google's, for Colab), so they hit the same blocks. If you have to use one, route its egress through a VPN or proxy that exits from a residential IP or a non-cloud institutional network; another datacenter exit (AWS and the like) will not clear the block.

<br>
<br>

## How to add a new probe

1. Pick the closest existing probe and copy its file. Most new probes look like `InfoProbe` (single REST call) or `SnapshotProbe` (REST call + per-route check function).
2. Set the three class attributes: `kind` (`"rest"` or `"ws"`), `route` (the capability key), `name` (what shows up in the JSON; usually equal to `route` unless you have sub-probes).
3. Implement `applies(ctx)`. Gate on `ctx.caps_slice.get(self.route, {}).get("rest")` (or `"ws"`) so the probe is only run when the adapter advertises the feature. Returning `False` for unsupported markets is correct, not lazy.
4. Implement `async run(ctx)`. Always:
   - Capture `started = time.time()` before the network call.
   - On non-200, return `[self.http_failure(ctx, self.name, started, status, data, err)]`.
   - On 200, validate shape with `validate_one` or `validate_list`, then route-specific invariants.
   - When inspecting nested value objects (`qty`, `volume`, `open_interest`, `funding`), read the typed fields (`row["qty"]["native"]`, `row["funding"]["kind"]`); the wire format never exposes them flat.
   - Build the success result with `self.result(ctx, self.name, started, status="pass", error_type=ErrorType.OK, message=..., evidence=...)`.
5. Register it in `probes/__init__.py`: append to `market_probes()` for per-market probes, or to `exchange_probes()` for top-of-exchange ones (rare, currently `ErrorPathProbe` and `StreamRefusalProbe`).
6. If you added a new route the adapters expose, also update `CapabilitiesConsistencyProbe`'s route list so drift is caught for it.

A new probe is ~50-80 lines. If yours is bigger, look at `PaginatedProbe` for how to split into sub-probe methods.

<br>
<br>

## Code conventions

- **Result construction**: always go through `self.result(...)` or `self.http_failure(...)`. No bare `ProbeResult(...)` calls inside probe code. The one exception is `PaginatedProbe._skip_anchors`, which constructs the result directly because the "skip" status has no `started` timestamp to measure against.
- **Evidence**: keep it small and machine-readable. Numbers, strings, flat dicts. The `body_preview` truncation in `http_failure` (200 chars) is the precedent.
- **No raw `print`**: console output is owned by `LiveReporter` and `render_failure_summary` in `output/live.py`. Use `logger` for anything else.
- **No mutation of `ProbeResult` outside `PaginatedProbe`**: the post-hoc `res.status = "fail"` pattern lives only inside `PaginatedProbe.run()` because its sub-probes need a two-phase verdict (data validity, then domain-specific check). Don't propagate it.
- **Throttling**: REST calls go through `fetch()` in `base.py`, which enforces `MIN_REST_INTERVAL_MS` per exchange. Don't bypass it.

<br>
<br>

## Interpreting failures

A FAIL in the report does not always mean an adapter regression. Rule out these before chasing a bug:

- **Upstream publish lag on analytics-style endpoints.** Some analytics endpoints (open interest, long/short ratio, similar aggregated stats) publish their buckets with a delay that fluctuates with upstream load. The `recent` sub-probe's freshness threshold defaults to `3 * period + 30s` (about 45 minutes for 15m); a slow window can push real lag above that. Re-run after 20 to 30 minutes. If the failure clears, it was transient upstream. If the same `(exchange, market_type, period)` keeps failing, add an entry to `config.py::FRESHNESS_OVERRIDE_MS`.

- **Quiet-market WebSocket activity.** `trades`, `agg_trades`, and `liquidations` depend on real events. On low-volume contracts a 180-second window can legitimately produce few or zero frames; KuCoin's inverse `XBTUSDM` trades about once every four minutes. Liquidations have threshold 0 for this reason, and an empty trade window the venue's own trades show was quiet is a SKIP.

- **Identical staleness across unrelated routes.** When two routes that share a bucket cadence (for example `candles:15m` and `open_interest:15m`) report byte-identical age, the cause is upstream cadence, not adapter logic. The auditor captures `now_ms` once at run start. Both probes measure against that snapshot, so an upstream that has not yet published its newest bucket leaks the same lag everywhere.

- **Rate limits.** Hyperliquid allows 1,200 weight a minute per IP; most reads weigh 20, and a large candle read up to about 100. The router answers the retries a throttled read exhausts with `503`, which is why the auditor spaces Hyperliquid's probes three seconds apart (`config.py::REST_INTERVAL_MS`).

- **Real upstream 5xx exhaustion.** When `_make_request` exhausts retries and surfaces a 500, the upstream had a real outage during the run. The auditor does not paper over it; the failure is honest but not actionable on the adapter side.

When in doubt: re-run with `--parallel 1 <exchange>` to isolate, and compare the FAIL `last_ts` value against the upstream's own public endpoint for that pair. If the upstream itself does not have the recent record, the auditor is reporting honestly.

<br>
<br>

## Coverage limits

The auditor is a route-and-shape verifier, not a full integration test. It does **not** test:

- Multiple symbols per market (one BTC/ETH-stable pair is picked per market, and one halted market where the list has one).
- WebSocket reconnect or heartbeat-silence behaviour. (Validates frame shape and minimum count over a sustained window; forced-disconnect tests are out of scope as flaky.)
- Concurrent or rate-limited access beyond the configured semaphores.
- Authenticated endpoints (the router currently exposes only public routes).
- Malformed input handling beyond the negative paths.
