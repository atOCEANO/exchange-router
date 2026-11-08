from exchange_router.rows import symbol_info_row


WITHOUT_BLOCKS = {
    "symbol":        "BTCUSDT",
    "market_type":   "linear",
    "native_symbol": "BTCUSDT",
    "status":        "trading",
    "base":          "BTC",
    "quote":         "USDT",
    "funding":       {"kind": "discrete"},
}


def test_a_symbol_row_reads_none_for_a_block_the_record_lacks():
    row = symbol_info_row(WITHOUT_BLOCKS)

    assert row.price_tick   is None
    assert row.qty_step     is None
    assert row.notional_min is None
    assert row.funding_kind == "discrete"
    assert list(row)[-4:] == ["notional_min", "funding_kind", "timestamp", "time_source"]
