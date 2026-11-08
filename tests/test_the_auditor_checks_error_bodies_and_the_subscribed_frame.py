from exchange_router.version import SCHEMA_VERSION
from tools.auditor.probes.errors import body_verdict
from tools.auditor.probes.websocket import stream_refusal_verdict, subscribed_verdict


UNKNOWN = {"error": "Unknown Symbol", "detail": "ZZZNOTREAL is not listed on okx spot; /okx/spot/markets lists the symbols"}


def test_an_error_answer_must_carry_its_status_its_title_and_a_sentence():
    assert body_verdict(400, UNKNOWN, 400, "Unknown Symbol") is None
    assert body_verdict(502, {"error": "Bad Upstream Response", "detail": "okx sent a page it could not read"}, 400, "Unknown Symbol") == "got 502 'Bad Upstream Response', expected 400 'Unknown Symbol'"
    assert body_verdict(404, {"detail": "symbol not found"}, 400, "Unknown Symbol") == "got 404 None, expected 400 'Unknown Symbol'"
    assert body_verdict(400, dict(UNKNOWN, detail=""), 400, "Unknown Symbol") == "the Unknown Symbol body carries no detail sentence"


def test_a_refused_stream_must_send_its_body_before_a_1003_close():
    assert stream_refusal_verdict(UNKNOWN, 1003) is None
    assert stream_refusal_verdict(UNKNOWN, 1011) == "the stream closed with 1011 after its Unknown Symbol body, where 1003 was due"
    assert stream_refusal_verdict(None, 1008) == "the stream sent None and closed with 1008, where an Unknown Symbol body was due"


def test_a_subscribed_frame_must_name_the_channel_the_symbol_and_the_schema_asked_for():
    said = {"channel": "trades", "symbol": "BTCUSDT", "schema_version": SCHEMA_VERSION, "ts": 1794107760386}

    assert subscribed_verdict(said, "trades", "BTCUSDT") is None
    assert subscribed_verdict(dict(said, symbol="ETHUSDT"), "trades", "BTCUSDT") == f"subscribed names ('trades', 'ETHUSDT', {SCHEMA_VERSION}), not ('trades', 'BTCUSDT', {SCHEMA_VERSION})"
