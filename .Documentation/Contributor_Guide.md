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

## Local Development

Most adapter work needs no service at all. Install the package editable and drive the adapter through `Router.local`, which is the same code path the service uses:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[server,test,audit]"
```

```python
from exchange_router import Router

r = Router.local(exchanges=["binance"])
print(r.get_candles("binance", "spot", "BTCUSDT", interval="1h", limit=5))
```

When you do need the HTTP surface, run it with autoreload rather than rebuilding the image on every change:

```bash
uvicorn exchange_router.service:app --reload --port 8040
```

On Windows, activate the venv with `.venv\Scripts\activate`. The `--reload` flag restarts the worker whenever a file under `exchange_router/` changes.

When something breaks, it helps to drop below the router entirely. Instantiate the adapter in a REPL and call its methods directly. The stack trace is cleaner, and you can inspect intermediate state without routing a request end to end.

<br>

### Dependencies

`pyproject.toml` is the only dependency source, and it is split so that what ships is smaller than what you develop against.

| Install | Carries | For |
| :--- | :--- | :--- |
| `pip install .` | httpx, pandas, websockets, pydantic, orjson | the Python API and local mode |
| `.[server]` | adds fastapi, uvicorn | running the service |
| `.[test]` | adds pytest, pytest-asyncio | the offline suite |
| `.[audit]` | adds rich | the auditor |

The split is load-bearing rather than tidy. The base install is what makes a library possible: FastAPI is not a dependency of using this, only of serving it, and CI asserts that a base install cannot `import fastapi`. Two dependency lists is how the pandas that the frame builders need went missing from the service image once already, which is why there is now exactly one.

**Adding a new dependency:** put it in the narrowest extra that needs it. A profiler or a debugging library that only you use belongs in neither; keep it in your own venv.

When iterating without `--reload`, set `--port` on the uvicorn command line directly; the `EXCHANGE_ROUTER_SERVICE_PORT` env var is only consumed by `docker-compose.yml` and is not read by the Python service.

<br>

### The documentation set

Everything lives in `.Documentation/`, one page per topic, plus the top-level README. There are no per-folder READMEs.

Every page opens with the wordmark, the badge row, and a nav strip listing all of them with the current page bolded. The strip is the only navigation, so adding a page means editing every other one. That is the cost of having no generated index, and at ten files it is small enough to pay.

The order of the strip is shared with the other Oceano repositories: Introduction, Python API, this repository's domain pages, Architecture, Decisions, its guides, then Contributor Guide near the end. `Python_API.md`, `Architecture.md` and `Decisions.md` carry those exact filenames in every repository that has them, so somebody moving between two of them finds the same page in the same slot.

[Migration](Migration.md) is deliberately absent from the strip. It is read once during an upgrade rather than kept open, and it is reachable from [Python API](Python_API.md) and from the release notes.

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

The images are numbered rather than named and the descriptive name survives only in their alt text: 204644 is the README hero, 204646 the REST lifecycle, 204647 the WebSocket fan-out, 204648 the startup lifecycle, 204649 the funding timelines, 204650 backward pagination, 204651 rate-limit and ban avoidance, 204652 the two backends. The first seven were reconstructed by reading the rendered PNG, because no source was ever kept, so a rerun redraws them rather than reproducing the originals; 204652 was authored from its source.

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

For exchange-specific behaviors (rate limit tiers, symbol translation quirks, API version notes) see [Exchange Notes](Exchange_Notes.md). For internal mechanics that adapter authors need but users do not, see [Adapter Internals](Adapter_Guide.md#adapter-internals) below.

<br>
<br>

## Testing

There are two suites and they answer different questions. The offline suite asks whether the two modes agree and whether the code still does what it did; the auditor asks whether an adapter is correct against its exchange. Neither substitutes for the other.

<br>

### The offline suite

`tests/` runs with no network, no container and no service. It swaps the adapter registry for a fake that returns constructed model instances, and drives the FastAPI app in-process over an httpx ASGI transport, so it runs on a blocked CI runner exactly as it runs on a laptop.

```bash
docker build --target test -t router-test .
docker run --rm router-test pytest -q
```

Verification runs in Docker. Run it that way rather than against your venv, so the result does not depend on what your machine happens to have installed.

**Every test body runs twice**, once against `LocalBackend` and once against `RemoteBackend` over the in-process app, and asserts the same frames, columns, dtypes, index, provenance and exception types from both. That parametrisation is the point of the suite. If you add a read method, add it to a body that both legs run; if you add a route, the route-coverage test will fail until the SDK method exists, and the reverse.

The fake adapter lives in `tests/fake_exchange.py` and is deliberately awkward in the ways real venues are: it carries contract-denominated quantities on its inverse market and base on the others, both funding conventions, and an open-interest series whose first row has no candle to join against. Build inputs in the test that uses them, so a reader sees the input and the expected frame side by side.

**What it does not cover.** Streaming, in either direction: an ASGI transport carries HTTP and not websockets, so the served side of a stream cannot be driven here.

<br>

### The auditor

Adapter compliance is validated via the auditor package at `tools/auditor/` (see [Auditor Guide](Auditor_Guide.md)). The runner reads `/{exchange}/capabilities` and runs only the probes that apply to the features the adapter claims to support, so an honest capabilities map is the difference between a clean test run and noise. All declared endpoints must pass before submitting a Pull Request.

It runs locally, not in CI: exchange APIs block the datacenter IPs that hosted runners issue from, so a GitHub Actions run fails on refused connections rather than real defects. See [Auditor Guide](Auditor_Guide.md#why-the-suite-runs-locally-not-in-ci) for the full reasoning, and that guide for the probe catalogue, env knobs, concurrency model, run output and CLI examples.

<br>

### What CI does check

`.github/workflows/ci.yml` runs on every push to `main` and every pull request. It cannot run the auditor, so it checks only what needs no upstream, in four jobs: every adapter package registers an adapter and declares a non-empty capabilities map and at least one market type; the package installs into a clean interpreter, imports, ships `py.typed`, and pulls no FastAPI on a base install; the image builds, boots, and answers on `/status`, `/version` and `/exchanges`; and the offline suite passes.

The first of those is the one worth knowing about. `load_exchanges()` catches and logs an adapter that fails to import, so a broken adapter does not stop the service, it just leaves it running with one exchange fewer and nothing anywhere fails. Counting the packages on disk against the registry is what turns that into a red build. Treat a green CI run as saying the package is assembled and the two modes still agree, never as saying an adapter is correct against its exchange; only an auditor run says that.

<br>
<br>

## Releasing

`VERSION` in `exchange_router/version.py` is the single source of the version, and **the tag must equal it**. CI enforces this rather than generating it: a workflow that wrote the version would leave a running container reporting a number that is in no commit. `v2.2.0` was tagged on a commit still reading `2.1.0` before the rule existed; every tag from `v2.2.1` on agrees, and the guard job is what keeps it that way.

To cut a release, bump `exchange_router/version.py` in its own commit (the history keeps these separate, `chore(version): bump service to X.Y.Z`), then tag `vX.Y.Z` and push the tag. `.github/workflows/release.yml` checks the tag against `exchange_router/version.py` and publishes a GitHub Release with generated notes. Both jobs in that workflow are gated on the tag ref, so a manual dispatch from the Actions tab runs neither of them; there is no way to dry-run the guard short of pushing a tag.

The release used to build and attach nothing, on the reasoning that a library has to arrive as a file while this was a service you run, so the artifact was the repository at the tag. Both halves of that stopped being true at 3.0.0. This is a library now, and the client no longer carries a separate number that a wheel could disagree with, so the release builds one `py3-none-any` wheel plus an sdist and attaches them. There is no platform matrix: it is pure Python, so one wheel covers every target.

<br>
<br>

## Service Lifecycle

The full startup, request and WebSocket lifecycles live in [Architecture](Architecture.md#startup-lifecycle), including the background warm and the log timeline it emits. What matters to an adapter author is short.

An adapter is started and stopped the same way in both modes, and it cannot tell which one it is in. In the service, the FastAPI lifespan manager walks the registry on startup and tears it down on shutdown. In local mode, `Router.local` warms the scope in the background, and `close()` shuts down every adapter in the process and empties the registry, so the next local router builds new ones. The adapter sees `preload()` then `shutdown()` either way.

So the adapter owes the lifecycle exactly two things: a correct `shutdown()` that closes every client it opened in `__init__`, and optionally a `_warm()` (see [The `_warm()` hook](Adapter_Guide.md#the-_warm-hook)) if startup prebuilding is worth it. An adapter that leaks on `shutdown()` used to leak only in a container that was about to exit; in local mode it leaks inside somebody's notebook.

Once `shutdown()` is correct and `python -m tools.auditor` passes cleanly, the adapter is ready for review.

<br>
<br>

