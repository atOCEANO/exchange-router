<h1>OCEΛNO <small><code>exchange-router-service</code></small></h1>


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
  <b>Contributor Guide</b> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## Contributor Guide

The router is extended through isolated exchange adapters. Almost every contribution lives in `exchange_router/exchanges/<name>/` and leaves the routing core untouched. This guide walks through the work in roughly the order you will do it: set up a local loop, build the adapter, satisfy the contract, follow the code standards, and run the test suite before opening a PR.

<br>

### Record construction, the short version

Every record (Trade, Candle, MarkPrice, etc.) goes through a `build_*` helper in `exchange_router/exchanges/base.py`. Adapters pass in raw upstream values; the builders construct the nested value objects and compute USD where derivable. The wire-format spec is in [HTTP Reference](HTTP_Reference.md#response-shapes); the builder signatures are below.

An inverse trade, where USD is computed as `native * contract_size` and is price-independent:

```python
from src.exchanges.base import (
    build_qty_value, build_volume_value, build_oi_value,
    build_funding_current, build_funding_historical, build_funding_convention,
)

trade = Trade(
    symbol      = "BTCUSD",
    market_type = MarketType.INVERSE,
    quote       = "USD",
    price       = 50000.0,
    qty         = build_qty_value(native=5, qty_unit="contract", contract_size=100.0, price=50000.0),
    side        = "buy",
    timestamp   = ts,
)
```

All adapter sites that construct records pass `quote = info.quote_asset` at the row level. Look up `info = await self._info_for(market_type, model_symbol)` once at the start of each route handler / stream generator and reuse for every record in the response.

Cycle length for funding lives in an adapter-internal `_funding_interval_cache: Dict[MarketType, Dict[str, int]]` keyed by model symbol. SymbolInfo's `funding: Optional[FundingConvention]` block carries only the categorical `kind` (no `cycle_ms`); MarkPrice and FundingRate row constructors read the actual cycle_ms from the internal cache.

<br>

### The `_warm()` hook

`BaseExchange` exposes `async def _warm(self) -> None` (default: no-op) as the override point for adapter prebuilding. Override it to declare what should be warmed at startup. The base class owns everything else: it spawns the warm in a background task during `preload()`, times each step, logs a structured timeline, and contains failures so one adapter's warm cannot block another.

Inside `_warm()`, call `await self._step("label", awaitable)` once per logical warm. Each step's start, duration, and outcome are logged automatically. Steps run sequentially within an adapter (a chronological per-adapter timeline in the log); cross-adapter parallelism is preserved by the background-task wrapping.

```python
async def _warm(self) -> None:
    await self._step("spot_info",    self._ensure_info_cache(MarketType.SPOT))
    await self._step("linear_info",  self._ensure_info_cache(MarketType.LINEAR))
    await self._step("inverse_info", self._ensure_info_cache(MarketType.INVERSE))
```

If a warm step has its own bounded-concurrency fan-out (per-symbol lookups with a semaphore, for example), put that logic in a regular adapter method and pass the call to `_step`. The semaphore guard and per-symbol failure handling stay outside `_warm()`, so the orchestration line reads as one intent:

```python
async def _warm(self) -> None:
    await self._step("linear_funding", self._warm_funding_intervals(MarketType.LINEAR))


async def _warm_funding_intervals(self, market_type: MarketType) -> None:
    cache = await self._ensure_info_cache(market_type)
    sem   = asyncio.Semaphore(2)
    tasks = [self._warm_one_funding_interval(info, sem) for info in cache.values()]

    await asyncio.gather(*tasks, return_exceptions=True)


async def _warm_one_funding_interval(self, info: SymbolInfo, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            await self._funding_interval_ms_for(info.native_symbol)
        except Exception as e:
            logger.warning(f"funding interval lookup failed for {info.native_symbol}: {e}")
```

By convention, `_warm()` (and any `_warm_*` helpers it calls) sits right after `shutdown()` in the adapter file; every existing adapter follows this placement. `_ensure_info_cache` and `_info_for` are provided by `BaseExchange` (see [SymbolInfo cache](#symbolinfo-cache-base-provided) below); the `_ensure_*_map` methods referenced in the examples are adapter-internal lazy caches. Listing either kind in `_warm` simply forces eager warming at startup.

Do not override `preload()` directly. The base class seals it; the override point is `_warm()`. If your adapter does not need prebuilding (one bulk endpoint covers all metadata), simply don't override `_warm`.

<br>
<br>

## Local Development

The service ships as a Docker container, but iterating on an adapter through `docker compose up --build` on every change is slow. For day-to-day work, run the service directly. Create the venv once, then activate it, install dependencies, and launch with autoreload:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8040
```

On Windows, activate the venv with `.venv\Scripts\activate`. The `--reload` flag restarts the worker whenever a file under `exchange_router/` changes. Pair it with the test suite running in another terminal for a tight edit-test loop.

<br>

### Dependencies

The repo has a single `requirements.txt` covering everything: the running service (FastAPI, uvicorn, httpx, websockets, orjson) and the local tools (rich, used by the auditor). The Dockerfile installs this file as-is, so the same dependency set is present in the production image and in a contributor's venv. There is no separate dev dependency file.

**Adding a new dependency:** put it in `requirements.txt`. If it is genuinely contributor-only (a profiler, a linter, a heavy debugging library), keep it out of the requirements file and document the install command in this guide instead, so the production image stays lean.

When something breaks, it helps to bypass FastAPI entirely. Instantiate the adapter in a Python REPL and call its methods directly. The stack trace is cleaner, and you can inspect intermediate state without routing a request end to end.

When iterating without `--reload`, set `--port` on the uvicorn command line directly; the `EXCHANGE_ROUTER_SERVICE_PORT` env var is only consumed by `docker-compose.yml` and is not read by the Python service.

<br>

### Documentation diagrams

`dev/diagrams/` holds the mermaid source for every hand-made diagram in `.Documentation/imgs/`, one `.mmd` per image, plus the shared palette in `config.json`. Nothing in the service depends on it and it is not installed anywhere; it exists so that no picture in the documentation is a file nobody can remake. Rendering the whole set writes straight into the image directory:

```bash
docker run --rm --shm-size=1g \
  -v "${PWD}/dev/diagrams:/diagrams" \
  -v "${PWD}/.Documentation/imgs:/out" \
  --entrypoint sh \
  minlag/mermaid-cli:11.17.1@sha256:062edb08dcc7f95841c15620241b6934af93aa75c27f223ebe2e81fd0b4da4c9 \
  -c 'set -e; for f in /diagrams/*.mmd; do n=$(basename "$f" .mmd); /home/mermaidcli/node_modules/.bin/mmdc -i "$f" -o "/out/$n.png" -c /diagrams/config.json -p /diagrams/puppeteer.json -b transparent -s 3; done'
```

The images are numbered rather than named and the descriptive name survives only in their alt text: 204644 is the README hero, 204646 the REST lifecycle, 204647 the WebSocket fan-out, 204648 the startup lifecycle, 204649 the funding timelines, 204650 backward pagination, 204651 rate-limit and ban avoidance. All seven were reconstructed by reading the rendered PNG, because no source was ever kept, so a rerun redraws them rather than reproducing the originals.

**Three things the setup depends on.** The image's bundled headless-shell is broken with an ENOENT, so `puppeteer.json` points `executablePath` at the chromium the image also ships, and its entrypoint is `mmdc` itself, so the command above clears it and calls the binary by full path. The background has to be `transparent` rather than white, or the images invert badly against GitHub's dark mode, which is what the replaced set did. And no `-w`: mermaid's own width keeps the wide diagrams at a consistent 2352 across, which is why the `width=` values in the pages can stay as they are.

**On rerunning.** The renderer is pinned to a digest rather than to `latest`, and that pin is what makes the paragraph below true over time rather than only within an afternoon: `latest` and the version tag are different images today, the tag names the mermaid version rather than the `mmdc` build inside it, and an unpinned rerun is free to relayout every picture at once. At this digest all seven come back byte identical, not merely at the pixel dimensions committed here, and two consecutive runs confirm it.

That last property is a property of the shapes as much as of the renderer, and it is worth knowing before adding a diagram. A stadium node's rounded outline anti-aliases a handful of edge pixels differently between runs, on the order of 0.013 percent of the image, so the five diagrams that used one were visually identical and never byte identical, and every rerun showed them as modified files carrying no change. They are rounded rectangles now, which read the same and are stable. The curve itself is not the problem, and 204644 is the evidence: its three cylinders and its one rounded node were byte identical throughout. Keep stadium nodes out of this set, and a rerun stays the check it is supposed to be, because any diff it produces is then a real one.

**The palette** in `config.json` is the same file emsl uses, so the two repos' diagrams are one visual set: node fill `#16232e`, a teal `#2ee6a6` border for anything the service does itself, a blue `#4d9feb` one for anything a caller or an upstream initiates, `#e6edf3` text, `#8b949e` arrows, trebuchet sans. Two classes are local to this repo, both on the rate-limit and lifecycle flows: `#c98500` for a degraded path that still returns, and `#ff5470` for a terminal one. It also names the cluster and edge-label colours, which look like padding and are not: mermaid derives whatever the palette leaves out, and left to itself it draws cluster frames as opaque brown boxes.

<br>
<br>

## Code Standards

* **Async I/O.** All network calls must use `httpx` or `websockets` in an async context. A blocking call inside an adapter stalls the entire event loop.
* **No raw dicts across the boundary.** Adapter methods must return Pydantic models from `exchange_router/models.py`. If you find yourself wanting to return a `dict`, add a model instead.
* **Fail with `ValueError`, `UpstreamUnavailableError`, or `NotImplementedError`.** These are the exception types the route layer knows how to translate into HTTP responses (400, 503, and 501 respectively). Use `ValueError` for bad input and upstream validation failures, `UpstreamUnavailableError` (from `exchange_router/exchanges/base.py`, optionally with `retry_after` seconds for the `Retry-After` header) for throttle and ban windows where the caller should retry later, and `NotImplementedError` for features the adapter does not support on a given market type. `UpstreamUnavailableError` is a subclass of `AdapterError`, not `ValueError`, and the route layer maps it to `503` through its own handler, so pagination loops that re-raise on `ValueError` do not swallow it.
* **No hand-rolled retry logic at the call site.** `_make_request` (or the adapter's equivalent) handles retries and backoff. Per-call retry loops fight the rate limiter.
* **Logging via `logging.getLogger("<adapter>_adapter")`.** Keep each adapter's logs isolated so they can be filtered independently.

For exchange-specific behaviors (rate limit tiers, symbol translation quirks, API version notes) see [Exchange Notes](Exchange_Notes.md). For internal mechanics that adapter authors need but users do not, see [Adapter Internals](#adapter-internals) below.

<br>
<br>

## Testing

Adapter compliance is validated via the auditor package at `tools/auditor/` (see [Auditor Guide](Auditor_Guide.md)). The runner reads `/{exchange}/capabilities` and runs only the probes that apply to the features the adapter claims to support, so an honest capabilities map is the difference between a clean test run and noise. All declared endpoints must pass before submitting a Pull Request.

The suite runs locally, not in CI: exchange APIs block the datacenter IPs that hosted runners issue from, so a GitHub Actions run fails on refused connections rather than real defects. See [Auditor Guide](Auditor_Guide.md#why-the-suite-runs-locally-not-in-ci) for the full reasoning.

See [Auditor Guide](Auditor_Guide.md) for the full probe catalogue, env knobs, concurrency model, run output, and CLI examples.

<br>

### What CI does check

`.github/workflows/ci.yml` runs on every push to `main` and every pull request. It cannot run the auditor, so it checks only what needs no upstream, and the list is deliberately short: every adapter package registers an adapter and declares a non-empty capabilities map and at least one market type, the client SDK installs into a clean interpreter and imports, and the image builds, boots, and answers on `/status`, `/version` and `/exchanges`.

The first of those is the one worth knowing about. `load_exchanges()` catches and logs an adapter that fails to import, so a broken adapter does not stop the service, it just leaves it running with one exchange fewer and nothing anywhere fails. Counting the packages on disk against the registry is what turns that into a red build. Treat a green CI run as saying the service is assembled, never as saying an adapter is correct against its exchange; only an auditor run says that.

<br>
<br>

## Releasing

`SERVICE_VERSION` in `exchange_router/version.py` is the single source of the version, and **the tag must equal it**. CI enforces this rather than generating it: a workflow that wrote the version would leave a running container reporting a number that is in no commit. `v2.2.0` was tagged on a commit still reading `2.1.0` before the rule existed; every tag from `v2.2.1` on agrees, and the guard job is what keeps it that way.

To cut a release, bump `exchange_router/version.py` in its own commit (the history keeps these separate, `chore(version): bump service to X.Y.Z`), then tag `vX.Y.Z` and push the tag. `.github/workflows/release.yml` checks the tag against `exchange_router/version.py` and publishes a GitHub Release with generated notes. Both jobs in that workflow are gated on the tag ref, so a manual dispatch from the Actions tab runs neither of them; there is no way to dry-run the guard short of pushing a tag.

The release builds and attaches nothing, which is deliberate. A library has to arrive as a file, so emsl ships wheels; this is a service you run, and the artifact is the repository at the tag, which GitHub attaches by itself. The release body carries the three things a reader actually needs instead: running it from a checkout without Docker, building the image from the same checkout, and installing the client. The client SDK carries its own version in `exchange_router/version.py` and installs straight from the tag, so publishing a wheel here would only produce a file whose number disagrees with the release it is attached to.

<br>
<br>

## Service Lifecycle

For reference, the router uses a FastAPI lifespan manager (`@asynccontextmanager`) to handle startup and shutdown. On startup, the auto-loader walks `exchange_router/exchanges/`, instantiates every `BaseExchange` subclass it finds, and registers it in `EXCHANGE_REGISTRY`. On shutdown, the manager closes all active WebSocket tasks cleanly and calls `shutdown()` on each adapter to release connection pools and any other resources the adapter holds.

Contributors rarely need to touch this layer. The adapter owes the lifecycle a correct `shutdown()` that closes every client it opened in `__init__`, and optionally a `_warm()` (see [The `_warm()` hook](#the-_warm-hook) above) if startup prebuilding is needed.

Once `shutdown()` is correct and `python -m tools.auditor` passes cleanly, the adapter is ready for review.

<br>
<br>

