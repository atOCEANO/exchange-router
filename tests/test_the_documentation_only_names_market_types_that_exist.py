import pathlib
import re

from exchange_router.models import MarketType


ROOT = pathlib.Path(__file__).resolve().parent.parent

PAGES = [ROOT / "README.md"] + sorted((ROOT / ".Documentation").glob("*.md"))

ADAPTERS = sorted(
    path.name for path in (ROOT / "exchange_router" / "exchanges").iterdir()
    if path.is_dir() and not path.name.startswith("__")
)

NAMES = "|".join(ADAPTERS)

CALL = re.compile(rf'\("({NAMES})",\s*"(\w+)"')

PATH = re.compile(rf'/({NAMES})/(\w+)/')

VALID = {market_type.value for market_type in MarketType}


def offenders(pattern):
    found = []

    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for exchange, market_type in pattern.findall(text):
            if market_type not in VALID:
                found.append(f"{page.name}: {exchange}/{market_type}")

    return found


def test_every_market_type_in_a_documented_call_is_a_real_one():
    assert offenders(CALL) == []


def test_every_market_type_in_a_documented_url_is_a_real_one():
    assert offenders(PATH) == []


def test_the_guard_is_reading_pages_and_finding_call_sites():
    matches = sum(len(CALL.findall(page.read_text(encoding="utf-8"))) for page in PAGES)

    assert len(PAGES) > 5
    assert matches > 10
