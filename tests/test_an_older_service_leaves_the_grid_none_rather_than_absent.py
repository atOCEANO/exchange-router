from exchange_router.rows import symbol_info_row


OLDER_BODY = {
    "symbol":             "BTCUSDT",
    "native_symbol":      "BTCUSDT",
    "base_asset":         "BTC",
    "quote_asset":        "USDT",
    "price_precision":    2,
    "quantity_precision": 3,
    "min_qty":            0.001,
    "max_qty":            1000.0,
    "min_notional":       50.0,
    "qty_unit":           "base",
    "contract_size":      None,
    "funding":            {"kind": "discrete"},
}


def test_a_symbol_row_from_an_older_service_reads_none_for_the_grid():
    row = symbol_info_row(OLDER_BODY)

    assert row.tick_size is None
    assert row.qty_step  is None
    assert list(row)[-3:] == ["tick_size", "qty_step", "funding_kind"]
