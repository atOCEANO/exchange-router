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
  <b>Architecture</b> &nbsp;•&nbsp;
  <a href="Decisions.md">Decisions</a> &nbsp;•&nbsp;
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## Architecture

One adapter per exchange behind a routing layer that never branches on which exchange it is calling, reachable two ways.

<br>

### One API, two backends

The Python API talks to a backend rather than to a URL. There are two, and they are the only thing that differs between the modes:

```text
Router  ->  LocalBackend   ->  adapters  ->  exchanges
Router  ->  RemoteBackend  ->  service   ->  adapters  ->  exchanges
```

The seam between the router and a backend is semantic, not URL-shaped. It carries a route name and the parts of a request that mean something (`exchange`, `market_type`, `symbol`, and the route's own parameters), so the local path never builds or parses a path string. `LocalBackend` calls adapter methods directly; `RemoteBackend` builds a URL, makes the request, and hands back the parsed body. Everything above the seam, the frame builders, the row builders, the market handle, provenance, warnings, batching and the error tree, is shared and never learns which one answered.

The service is one deployment of the same library. `exchange_router/service/main.py` is a FastAPI app over the same adapters and the same shared logic, and the only thing it adds is HTTP, the exception handlers that turn faults into status codes, and the WebSocket fan-out. REST and WebSocket share the port and the adapter instance.

<div align="center">
  <img src="imgs/204652.png" alt="One API, two backends, rejoining at the adapters" width="46%" />
  <p style="margin: 0;"><i>One path above the seam, two through it, one below. Everything down to the seam is shared and is never told which backend answered; everything below it is the same adapters reached from a different process</i></p>
</div>

The two paths are not kept in agreement by discipline. Every test body in the suite runs against both backends and asserts the same frames, dtypes, index, provenance and exception types, which is what [0005](Decisions.md) records and why that suite exists.

<br>
<br>

## Core Design

The router uses an abstract base contract (`BaseExchange`). Each exchange is an isolated adapter that implements it; the routing core never needs to know which exchange it is talking to. The loader in `exchange_router/exchanges/__init__.py` scans the directory at startup, instantiates every `BaseExchange` subclass it finds, and registers them in `EXCHANGE_REGISTRY`. Adding a new exchange is a matter of dropping a compliant adapter into that directory and restarting.

The wire contract is pinned to an integer `schema_version` field returned at `GET /`; the full record shapes live in [HTTP Reference](HTTP_Reference.md#response-shapes). Adapters never construct nested value objects by hand: they call shared `build_*` helpers in `exchange_router/exchanges/base.py` (`build_qty_value`, `build_volume_value`, `build_oi_value`, `build_funding_current`, `build_funding_historical`, `build_funding_convention`). This keeps the conversion logic in one place and the adapter authoring cost low.

Before deploying outside localhost, see [Security and Exposure](#security-and-exposure).

<br>
<br>

## Startup Lifecycle

The FastAPI `lifespan` handler in `exchange_router/service/main.py` awaits `startup_exchanges()` from `exchange_router/exchanges/__init__.py`, which runs the first two of three phases:

1. **Adapter loading.** `load_exchanges()` scans `exchange_router/exchanges/` and instantiates every `BaseExchange` subclass. Each adapter's `__init__` is synchronous and lightweight; it does not hit the network.
2. **Preload.** `startup_exchanges()` then walks `EXCHANGE_REGISTRY` and calls `await adapter.preload()` on each entry, each call wrapped in a `try`/`except` that logs the traceback and moves to the next adapter, so one adapter failing to warm does not stop the others or the boot. `preload()` is a sealed template on `BaseExchange`: if the adapter overrides `_warm()`, the base class spawns it as a background task and returns immediately. Startup does not block on the warm; the router accepts traffic right away. Inside `_warm()`, adapters call `await self._step("label", awaitable)` once per logical warm; the base class times each step and emits a structured log timeline (`[adapter] preload: warming X...`, `[adapter] preload: X ready in Ts`, `[adapter] preload: done in Ts`). Cross-adapter parallelism is preserved (each adapter's warm chain runs in its own background task); within an adapter, steps run sequentially so the log reads as a chronological per-adapter timeline. During the warm window any route that depends on a cache being primed triggers the same fetch the warm step would have performed (the first request to need it does the work under the cache lock, and the warm step finds it already filled); OKX funding intervals additionally fall back to a per-symbol on-demand lookup. Correctness is preserved either way at the cost of a few extra upstream calls until the warm catches up. SymbolInfo caches are owned by `BaseExchange` and refresh at most once per 24 hours after the initial fill; a failed refresh serves the cached copy and retries after an hour.
3. **Yield.** The service is now serving. Shutdown reverses this: stream-manager teardown first, then, per adapter, the preload warm task is cancelled and `adapter.shutdown()` closes the HTTP client and WS connections. Cancelling first is what stops a warm still in flight from calling a client that has just been closed.

<div align="center">
  <img src="imgs/204648.png" alt="Startup lifecycle with background warm" width="40%" />
  <p style="margin: 0;"><i>Each adapter declares its warm steps in `_warm()`; the base class spawns the chain in a background task and returns immediately, so the router accepts traffic without waiting</i></p>
</div>

<br>
<br>

## Request Lifecycle

Every REST request follows the same path:

<div align="center">
  <img src="imgs/204646.png" alt="REST request lifecycle" width="40%" />
  <p style="margin: 0;"><i>REST lifecycle: route validation, adapter dispatch, retry-aware upstream call, Pydantic normalization, JSON response</i></p>
</div>

<br>

The route resolves the exchange name to its registered adapter, the adapter makes an async upstream call, and the raw JSON is mapped to a Pydantic model from `exchange_router/models.py` before returning. Raw dicts never cross the boundary.

<br>
<br>

## WebSocket Lifecycle

WebSocket streams do not follow the same path as REST. The `StreamManager` in `exchange_router/service/stream_manager.py` sits between clients and the adapter's streaming methods.

When a client subscribes to a `(channel, symbol)` tuple on an exchange, the manager builds a key of the form `{exchange}:{market_type}:{channel}:{symbol}` and checks whether an upstream task already exists for it.

<div align="center">
  <img src="imgs/204647.png" alt="WebSocket fan-out lifecycle" width="85%" />
  <p style="margin: 0;"><i>One upstream WebSocket per (channel, symbol) tuple, fanned out to every attached client; cancelled when the last subscriber leaves</i></p>
</div>

<br>

1. **First subscriber.** The manager starts an async task that opens a single upstream WebSocket via `adapter.stream_*(market_type, symbol)`. Every message produced by the adapter is fanned out to all local clients registered under the same key.
2. **Additional subscribers.** New clients attach to the existing task. No new upstream connection is opened, which keeps the router well under per-IP connection limits on exchanges that enforce them.
3. **Last subscriber leaves.** The manager cancels the upstream task and releases its resources. The next subscriber to the same tuple starts a fresh connection.
4. **Upstream failure.** If the adapter's stream terminates (network drop, exchange-side reset), the manager closes every attached client with code `1011` and clears the entry. Clients are expected to reconnect and re-subscribe.

This is also why re-subscribing on the same connection is not supported. Each connection is bound to one stream task, and the router has no mechanism for moving a client between tasks.

<br>
<br>

## Rate Limiting

The backoff and fail-fast flow lives here; user-facing behaviour and per-exchange specifics live in [Exchange Notes](Exchange_Notes.md#rate-limit-and-ban-protection); implementation patterns and header names live in [Adapter Guide](Adapter_Guide.md#rate-limit-headers-and-proactive-backoff).

**The budget is per process, and in local mode that process is yours.** All of the machinery below lives in the adapter, so it protects one Python process and nothing more. A service coordinates because every caller shares one set of adapters and therefore one budget. Two notebooks in local mode are two budgets, and the exchange sees the sum of both while neither can see the other. That is the entire operational difference between the modes, and it is why [Which mode to use](../README.md#which-mode-to-use) draws the line at more than one of anything rather than at how serious the work is.

Each adapter holds a shared `_backoff_until` timestamp guarded by an `asyncio.Lock` (Binance keys it per upstream host, since api, fapi, and dapi carry independent weight buckets). Requests run in parallel by default, but every request consults the timestamp before issuing and sleeps until it clears if a backoff window is active. The lock only protects writes to the timestamp; reads are racy but harmless because the worst case is one extra request slipping through the boundary of a window. When the remaining backoff is large, some adapters fail fast with an `UpstreamUnavailableError` rather than blocking the caller: Bybit and KuCoin fail at 30s, OKX at 60s. Binance sleeps through the backoff and retries, using the upstream's `Retry-After` header (or 5s default) for rate-limit waits with up to 3 retries; Kraken waits out any deadline the upstream declares (a `Retry-After` header, or a throttle time parsed out of the error body) and otherwise doubles a one-second base per attempt, caps that base at 60s, then scales it by a random 0.5x to 1.5x jitter factor, so a single wait can reach 90s; the budget is 8 attempts on Spot REST and 5 on Futures, after which it fails with `UpstreamUnavailableError`. Per-adapter specifics live in [Exchange Notes](Exchange_Notes.md#rate-limit-and-ban-protection).

<div align="center">
  <img src="imgs/204651.png" alt="Rate-limit and ban avoidance" width="40%" />
  <p style="margin: 0;"><i>Binance's per-request path, the most instrumented of the six: wait out any active host backoff, throttle proactively once the used-weight header passes 95 percent of that host's budget, honor Retry-After on 429 or 418, and fail with 503 plus Retry-After once the retries are spent. The backoff window and the retry ladder are common to every adapter; the weight header is Binance's alone</i></p>
</div>

<br>
<br>

## Error Handling

The router normalizes failures into a small set of HTTP responses. It helps to separate what adapters raise from what the route layer emits, because adapter authors only need to worry about the first list.

Adapters raise four exception types:

* **`ValueError`** for bad input or upstream validation failures (unknown symbol, out-of-range limit, an interval or period not declared in the capability map, adapter-side parameter rejections). A global exception handler in `main.py` converts these into `400 Bad Request`, preserving the message in `detail`. The route layer itself raises `ValueError` for undeclared `interval` / `period` values before the adapter is called, validated against the capability map.
* **`UpstreamUnavailableError`** (defined in `exchange_router/exchanges/base.py`, a subclass of `AdapterError`, not `ValueError`) when the upstream is throttling or has banned the IP: active backoff windows past the adapter's fail-fast threshold (30s on Bybit and KuCoin, 60s on OKX), Bybit 403 bans, an upstream 5xx that survives the retry budget, and any adapter's exhausted retry budget (message `"Max retries exceeded for {url}"`). The handler in `main.py` converts these into `503 Service Unavailable` with a `Retry-After` header when the adapter knows the wait.
* **`NotImplementedError`** when the adapter does not implement a method for a given market type. The base class raises this by default, and the route layer catches it and returns `501 Not Implemented`.
* **`pydantic.ValidationError`** when an upstream response cannot be normalized into the schema. A `ValidationError` is not a `ValueError` in pydantic v2, and its own handler in `main.py` returns `502 Bad Upstream Response`. Any other uncaught exception falls through to a generic handler that returns `500 Internal Server Error`.

The route layer adds three more responses that adapters never raise themselves:

* **`404 Not Found`** when the exchange name is not in `EXCHANGE_REGISTRY`. Raised directly by `validate_request` before the adapter is ever called.
* **`400 Bad Request`** when the market type is known but the adapter does not declare support for it. Also raised by `validate_request`, checked against each adapter's `supported_market_types` list.
* **`422 Unprocessable Entity`** when a path or query parameter fails FastAPI's pydantic validation (for example, an unrecognised `market_type` enum value). Raised by FastAPI before the route handler runs.

One more condition does not correspond to an exception type at all:

* **Upstream rate limiting** (429 or 418, or proactive detection via response headers) causes the adapter to wait for the declared backoff window before retrying. The client request is delayed, not rejected. When the wait exceeds the adapter's fail-fast threshold (30s on Bybit and KuCoin, 60s on OKX), the adapter raises `UpstreamUnavailableError` instead, which falls under the second bullet above. Binance and Kraken do not implement a single fail-fast cutoff; they sleep and retry until the upstream clears or the retry budget exhausts, then raise `UpstreamUnavailableError` (Kraken retries 8 times on Spot REST and 5 on Futures, and its waits are exponential to a 60s ceiling with 0.5x to 1.5x jitter, so a Spot budget runs out after roughly 1 to 3 minutes).

The `detail` field in error responses always carries the underlying exception message, whether it came from the adapter or the upstream exchange. Nothing is rewritten or swallowed.

<br>
<br>

## Versioning Policy

The router carries two version numbers, defined in [exchange_router/version.py](../exchange_router/version.py). Only one of them is a compatibility claim.

* **`VERSION`** is the standard semver string (`MAJOR.MINOR.PATCH`). It bumps for any user-visible change: a new route, a new field, a behavioural fix, a capability adjustment, a dependency upgrade. Returned at `GET /version` and `GET /`.
* **`SCHEMA_VERSION`** is a small integer. It bumps only when the wire format breaks consumer code: renaming a field, flattening a nested object into top-level fields, removing a discriminator value, changing the type of a field. Adding an optional field does not bump. Returned at `GET /` and stamped on every auditor `results.json` and on every DataFrame's `.attrs`; the auditor compares served-against-pinned and fails the suite on drift.

The two are decoupled on purpose. A wire-compatible bug fix bumps `VERSION` and leaves `SCHEMA_VERSION` untouched, so clients pinned to a schema number do not need to change. A genuine wire break bumps both.

**Compatibility is gated on the schema number and never on the release number.** In service mode the SDK reads `GET /version` once, on the first call that needs capabilities, and raises `SchemaMismatch` if the integers disagree. Gating on `VERSION` instead would mean a patch release of the container breaking every pinned install, and the two could never be deployed independently. The cost of that choice is recorded in [0004](Decisions.md): because additive fields never move the schema, the frame builders must tolerate a column that is not there rather than raising.

The check runs on the first request rather than at construction, because a constructor cannot await a round trip. It costs nothing extra: the SDK already makes a lazy first call to fetch capabilities, and the handshake rides along with it.

<br>
<br>

## Deployment Notes

The router is designed to run as a single container per exchange IP. A few consequences follow from that.

* **Rate limit state is in-memory.** Each router instance tracks its own backoff timestamps and per-adapter locks. Running two router instances behind a load balancer that both hit the same exchange from the same IP will double-count request weight and risk an IP ban. If you need horizontal scaling, shard exchanges across instances rather than replicating them.
* **No persistence.** The service holds no database, no cache, no on-disk state. Historical data is always pulled from upstream on demand. A restart loses only in-flight requests and WebSocket sessions.
* **No built-in observability.** The router logs to stdout via Python's `logging` module. Metrics and traces are not emitted. If you need them, wrap the service at the edge (reverse proxy, sidecar) or add them directly to the adapter layer.
* **CORS is open.** `allow_origins=["*"]` is set so any local client can talk to the router during development. If you expose the router beyond localhost, put it behind a proxy that enforces origin checks.

These are intentional constraints that keep the service stateless and straightforward to restart. Understand them before pointing real traffic at the service.

<br>
<br>

## Security and Exposure

The router is designed for localhost or a trusted network. It ships without authentication, inbound rate limiting (only outbound), request signing, TLS termination, or origin enforcement. Anyone who can reach the port can issue any request the adapters support.

Every response is public market data, so a compromised router cannot leak private information or move funds. The real risk is being abused as an open proxy: a misbehaving caller hammering upstream exchanges from your IP. That is how IP bans happen.

If you run the router outside a trusted network, put it behind a reverse proxy that adds TLS, an allowlist or origin check, and an inbound rate limit tight enough that one misbehaving client cannot exhaust the upstream budget. A minimal nginx or Caddy config is enough. Per-client quotas, audit logging, and API keys belong in that proxy layer, not in the router. If you run multiple Oceano services behind the same proxy, give the router its own subpath or hostname and keep the port private; CORS is wildcard-open by design for local development.
