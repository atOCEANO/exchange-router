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
