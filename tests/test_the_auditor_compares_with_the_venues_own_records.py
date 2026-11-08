import pytest

from tools.auditor.config import INSTRUMENTS
from tools.auditor.probes.base import dig, fill
from tools.auditor.probes.info import instrument_findings, venue_grid
from tools.auditor.probes.snapshot import estimate_verdict, price_verdict


OKX_LINEAR = {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01", "maxLmtSz": "100000000", "ctVal": "0.01"}]}

ROUTER_OKX_LINEAR = {
    "price": {"kind": "tick", "tick": 0.1, "decimals": 1},
    "qty":   {"unit": "base", "contract_size": None, "step": 0.0001, "decimals": 4, "min": 0.0001, "max": 1000000.0},
}


def test_a_path_reads_through_a_keyed_result_and_finds_a_record_by_its_fields():
    kraken  = {"error": [], "result": {"XBTUSDT": {"tick_size": "0.1", "lot_decimals": 8}}}
    binance = {"symbols": [{"symbol": "ETHUSDT"}, {"symbol": "BTCUSDT", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.10"}, {"filterType": "LOT_SIZE", "stepSize": "0.001"}]}]}

    assert dig(kraken, ("result", "*", "lot_decimals")) == 8
    assert dig(binance, fill(("symbols", {"symbol": "{native}"}, "filters", {"filterType": "LOT_SIZE"}, "stepSize"), "BTCUSDT")) == "0.001"
    assert dig(binance, ("symbols", {"symbol": "XRPUSDT"}, "filters")) is None


def test_okx_lots_count_in_contracts_and_the_record_is_compared_in_the_coin():
    venue = venue_grid(OKX_LINEAR, INSTRUMENTS[("okx", "linear")][2], "BTC-USDT-SWAP")
    wrong = dict(ROUTER_OKX_LINEAR, qty=dict(ROUTER_OKX_LINEAR["qty"], step=0.01))

    assert venue == {"tick": 0.1, "step": pytest.approx(0.0001), "min": pytest.approx(0.0001), "max": pytest.approx(1000000.0)}
    assert instrument_findings(ROUTER_OKX_LINEAR, venue) == []
    assert instrument_findings(wrong, venue) == [{"field": "step", "router": 0.01, "venue": venue["step"]}]
    assert set(venue_grid({}, INSTRUMENTS[("okx", "linear")][2], "BTC-USDT-SWAP").values()) == {None}


def test_a_price_must_lie_within_the_venues_own_reading_either_side_of_it():
    assert price_verdict(100_050.0, 100_000.0, 100_100.0) is None
    assert price_verdict(100_140.0, 100_000.0, 100_040.0) is None
    assert price_verdict(101_000.0, 100_000.0, 100_040.0) == "price 101000.0 lies outside 100000.0 to 100040.0, the venue's own reading either side of it"


def test_an_estimated_deadline_must_lie_within_one_cycle_of_now():
    now = 1794107760386

    assert estimate_verdict(now + 1_800_000, 3_600_000, now) is None
    assert estimate_verdict(now + 7_200_000, 3_600_000, now) == "the estimate lies 7200s from now, beyond one cycle of 3600s"
