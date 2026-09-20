import pathlib
import re
import subprocess
import sys


ROOT = ROOT = pathlib.Path(__file__).resolve().parent.parent

PACKAGE = ROOT / "exchange_router"

SDK_MODULES = {
    "__init__.py", "_core.py", "_warnings.py", "async_router.py", "backend.py",
    "batch.py", "capabilities.py", "errors.py", "frames.py", "funding.py",
    "handle.py", "models.py", "router.py", "rows.py", "version.py",
}

LEAVES = ("models.py", "errors.py", "capabilities.py")


def importers(module: str):
    pattern = re.compile(rf"^\s*(?:from|import)\s+{module}\b", re.MULTILINE)
    found   = set()

    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(PACKAGE).as_posix())

    return found


def flat_modules(paths):
    return {p for p in paths if "/" not in p}


def test_the_package_lists_exactly_the_flat_modules_this_file_knows_about():
    on_disk = {p.name for p in PACKAGE.glob("*.py")}
    assert on_disk == SDK_MODULES


def test_fastapi_lives_only_in_the_service_folder():
    assert importers("fastapi") | importers("starlette") == {
        "service/main.py",
        "service/stream_manager.py",
    }


def test_the_transport_is_behind_the_seam_and_nowhere_else_in_the_sdk():
    for transport in ("httpx", "websockets"):
        assert flat_modules(importers(transport)) == {"backend.py"}


def test_the_adapters_may_hold_a_transport_because_they_are_the_transport():
    for transport in ("httpx", "websockets"):
        assert any(p.startswith("exchanges/") for p in importers(transport))


def test_pandas_never_reaches_the_adapters_or_the_service():
    holders = importers("pandas")
    assert holders == flat_modules(holders)
    assert holders == {"frames.py", "funding.py", "router.py", "_core.py"}


def test_the_three_leaves_import_nothing_from_the_package():
    for leaf in LEAVES:
        source = (PACKAGE / leaf).read_text(encoding="utf-8")
        assert "from exchange_router" not in source
        assert not re.search(r"^\s*from \.", source, re.MULTILINE)


def test_the_adapters_never_import_the_sdk_half():
    sdk = {m[:-3] for m in SDK_MODULES} - {"models", "capabilities", "errors", "version"}

    for path in (PACKAGE / "exchanges").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for module in sdk:
            assert f"exchange_router.{module}" not in source, f"{path.name} imports {module}"


def test_importing_the_package_constructs_no_adapters():
    code = (
        "import exchange_router, exchange_router.backend;"
        "from exchange_router.exchanges import EXCHANGE_REGISTRY;"
        "print(len(EXCHANGE_REGISTRY))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0"
