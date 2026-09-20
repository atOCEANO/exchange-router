import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parent.parent

FASTAPI_IS_ALLOWED_IN = {
    "src/main.py",
    "src/stream_manager.py",
}

PATTERN = re.compile(r"^\s*(?:from|import)\s+(fastapi|starlette)\b", re.MULTILINE)


def python_files(*roots):
    for root in roots:
        for path in (ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def importers_of_fastapi():
    found = set()
    for path in python_files("src", "client", "tools"):
        if PATTERN.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(ROOT).as_posix())
    return found


def test_only_two_modules_import_fastapi():
    assert importers_of_fastapi() == FASTAPI_IS_ALLOWED_IN


def test_the_sdk_never_imports_fastapi():
    sdk = {p for p in importers_of_fastapi() if p.startswith("client/")}
    assert sdk == set()


def test_the_adapters_never_import_fastapi():
    adapters = {p for p in importers_of_fastapi() if p.startswith("src/exchanges/")}
    assert adapters == set()
