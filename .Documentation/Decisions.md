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
  <b>Decisions</b> &nbsp;•&nbsp;
  <a href="Migration.md">Migration</a> &nbsp;•&nbsp;
  <a href="Adapter_Guide.md">Adapter Guide</a> &nbsp;•&nbsp;
  <a href="Contributor_Guide.md">Contributor Guide</a> &nbsp;•&nbsp;
  <a href="Auditor_Guide.md">Auditor Guide</a>
</sub>

<br>
<br>
<br>
<br>

## Decisions

The record starts at 3.0.0 and is not backfilled. Everything before it was decided without one, and inventing numbers for choices nobody wrote down at the time would make the history look more deliberate than it was. Commit messages here do not cite these numbers; that convention belongs to a sibling repository and mixing the two would leave this history inconsistent with itself.

Each entry is one paragraph. It says what was decided, and it says what the decision costs, because a decision with no cost recorded is usually one that was never actually made.

<br>

**0001 One API, two backends.** The repository offered the HTTP service and an SDK that existed only to call it, and a third importable library was proposed. Three surfaces to learn, two of them returning different types. Instead the SDK gained a backend it talks through: `LocalBackend` calls the adapters in this process, `RemoteBackend` speaks HTTP to a running service, and the seam between them is semantic rather than URL-shaped, so the local path never parses a path string. The entire user-facing decision becomes which constructor is called. The cost is that two code paths must agree forever, which is what 0005 exists to enforce.

**0002 The seam carries wire-shaped dicts, not models.** A model-level boundary would let the remote side validate what it parsed, and it was rejected. `frames.py` and `rows.py` consume dicts today, and moving the boundary to models means rewriting both builders, which is a large change to the exact code the suite is protecting. Dicts keep both untouched and still prove the two backends agree. The cost is that a malformed response from a service is caught later than it could be; validation can be added inside the one method that owns the seam without moving it.

**0003 Mode and scope are required, and nothing is inferred.** `Router.local` and `Router.service` both demand the exchange scope, and bare `Router(...)` raises. Mode is never inferred from an absent URL, because an unset configuration variable arriving as `None` would silently select local mode and hand a caller a private per-process rate budget when they asked for the shared one. Config-driven code branches explicitly. The cost is verbosity at every call site, accepted because a default can be added later without breaking anyone and cannot be removed later without breaking everyone.

**0004 `SCHEMA_VERSION` bumps only on a breaking wire change.** It is a contract number, not a release number, and additive fields do not move it. A mismatch is therefore unambiguous and fatal, with no compatibility ranges to maintain, and the SDK gates on it rather than on the release version so a patch release of the container does not break every pinned install. The cost is that the SDK can never assume a field is present, so the frame builders tolerate a missing column rather than raising.

**0005 Parity is enforced by a shared suite, not by structure.** The service could have become a one-line shell over the local backend, which would make the two modes structurally incapable of disagreeing. It was rejected because the route bodies are already pass-throughs, so the rewrite buys a property the suite already enforces while touching every shipped, audited route. Instead every test body runs against both backends. The cost is that five response envelopes exist twice, once in the service and once in the local backend, and only a test keeps them equal.

**0006 The package is flat at the repository root.** `exchange_router/` sits at the top level and the library modules sit directly inside it. There is no `src/`, and no `client/`, `sdk/` or `api/` folder, because the library is not a part of the package, it is the package; the service is what becomes subordinate, since it is one deployment of the library rather than a peer. Keeping `src/` on disk and renaming it at build time was possible and was rejected: the package would carry two names, and with mutable module-level state in the adapter registry, two names load two copies of it.

**0007 The capability lookup lives in a leaf.** Reading a route block out of a capabilities map was duplicated in four places, and the obvious home for the shared version was `exchanges/base.py` beside the other shared helpers. That would have made the SDK's preflight import the adapter base, dragging httpx, orjson and every model into service mode. It lives in `capabilities.py` instead, which imports only `typing`. The package now has three such leaves, `models.py`, `errors.py` and `capabilities.py`, and anything may depend on them because they depend on nothing.

**0008 The auditor's dependencies are not the service's.** `rich` was a service dependency only because one requirements file served both. The auditor is a developer tool that talks to the service over HTTP and has no business inside its image, so it has its own extra. The cost is that running the auditor now means installing that extra rather than exec-ing into a running container.

**0009 A closed router raises rather than waits.** `Router.close` stopped the loop thread without closing the loop, so every later call queued a callback onto a loop that would never run again and then blocked on a future that would never resolve. A second `close()`, which is what a `with` block does after an explicit one, hung the same way. The loop thread now records that it is closed, closes the loop once the thread has actually joined, and every entry point checks that flag first. The cost is an error where there used to be a wait, which is a change only for code that never returned.

**0010 `close()` empties the adapter registry.** The registry is module-global and shared by every local router in the process, and shutdown walks all of it rather than one router's declared scope. Leaving the closed adapters registered meant the next `Router.local(...)` skipped loading and handed back objects whose HTTP clients were already closed, so the recommended `with` block was single use. Shutdown now clears the registry and the next local router builds fresh adapters. The cost is that a second live router in the same process loses its warm caches when the first one closes; reference counting the registry would avoid that, and buys correctness for a case the library does not otherwise support.

**0011 Retryability is carried by the exception type.** `_core.stream` decides whether to reconnect by asking whether the error is a websockets error or an `OSError`, and the local backend mapped every fault to a `RouterError` before it could be asked, which left `reconnect=True` inert in local mode while it worked over HTTP. The local backend now lets a retryable transport error through untouched and maps only the rest. The cost is that one class of exception crosses the backend seam unwrapped, so the seam is no longer "everything becomes a `RouterError`", and a final failure surfaces as the transport's own type.

**0012 A fatal close code becomes a typed error.** The service refuses a bad subscription by closing the socket, and the client handed the raw `websockets.ConnectionClosed` to the caller, so the same mistake raised `NotSupported` locally and an exception outside the error tree remotely. Codes 1003 and 1008 now become `NotSupported` and `BadRequest` carrying the close reason, and a handshake the service rejects before accepting becomes `NotFound` instead of retrying forever. Every other close stays a `ConnectionClosed`, because that is the drop the reconnect path exists to absorb. The cost is that the close codes are now part of the wire contract.

**0013 `"all"` is resolved where it can be known.** In local mode the registry answers `exchanges="all"` at construction. In service mode there is nothing to ask until the first call, and the scope was left empty, which turned off background warming and the served-exchange check and made `.scope` read back empty for the life of the router. The handshake already fetches the served list, so it fills the scope in. The cost is that `.scope` reads empty until the router has spoken to the service once, which makes it a report of what the router knows rather than of what the caller typed.

**0014 The capability cache holds successes only.** A failed capability fetch was stored as an empty block and the cache is keyed on presence, so one transient error disabled preflight for the life of the router and every later invalid interval or unsupported route went to the upstream instead of being refused locally. Failures are no longer stored, and `get_capabilities` raises rather than returning the empty block, so a caller can tell an exchange that publishes nothing from a service that could not be reached. The cost is that a service which is down is asked again on every call rather than once.

**0015 Every read goes through the handshake.** `SchemaMismatch` is documented as arriving on the first call, and eight discovery methods reached the backend directly, so a router whose first call was `get_markets` or `get_symbol_info` parsed a foreign schema without complaint. They now go through one helper that runs the handshake first. The cost is one extra round trip on the first call of a service-mode router, and that the handshake's own two fetches stay on the raw path so they do not recurse.

**0016 Degradation is announced, and it is one-way.** `fallback="local"` switched backends on an unreachable service and said nothing, handing a caller who asked for the shared rate budget a private per-process one without a signal, which is what 0003 refuses to do silently at construction. The switch now warns and is readable as `.degraded`, streams fall back where they did not before, and the local adapters are warmed by the next `warm()`. The cost is a warning on a path that was silent, and that degradation lasts for the life of the router, since nothing probes for the service coming back.

**0017 A closed router refuses work in both of its forms.** 0009 gave the sync router a loop thread that raises rather than waits and left `AsyncRouter` without an equivalent, which made the rule half true in a way the page stated whole. After `await close()` a service-mode call surfaced httpx's own `RuntimeError`, outside the error tree, and a local-mode call quietly reloaded the registry that `close()` had just emptied and then succeeded, resurrecting adapters that had been shut down on purpose. `AsyncCore` now records that it closed, closing twice is a no-op, and the entry points that reach a backend check it first. The cost is a second flag that has to stay true, and that anyone leaning on the local-mode resurrection now gets an error instead; nobody could have leaned on it deliberately, since it was neither documented nor intended.

**0018 A stream told not to reconnect ends when the upstream ends.** The retry loop is a `while True`, and a subscription that finished cleanly left the `async for` without raising, so the loop went round and subscribed again even when the caller had passed `reconnect=False`. Against a real feed this never showed, because an exchange socket does not end on its own; against anything finite it was an endless resubscribe. `reconnect=False` now means one subscription, which is what it reads as and what `subscribe` already did. The cost is that the two now differ only in whether a drop is retried, a thinner line than the names suggest.

**0019 The build context keeps the documentation markdown.** `.dockerignore` excluded `.Documentation` outright, the image is built with `COPY . .`, and the suite runs inside that image, so a test that reads the pages could not pass where tests are allowed to run: the guard that checks every market type named in the documentation against `MarketType` saw one page instead of ten and failed its own anti-vacuity assertion. The markdown is re-included and the diagrams stay excluded, which is where the weight is, 232 KB against 2.1 MB. The cost is that the service image now carries the prose as well as the code, to serve a test only the test stage runs.
