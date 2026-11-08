from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


SCHEMA_VERSION = 3

USD_FAMILY = {"USD", "USDT", "USDC", "USDD", "TUSD", "FDUSD", "BUSD", "DAI", "PYUSD", "USDE", "USDP"}

TEXT_COLUMNS = {"side", "id", "agg_id", "first_trade_id", "last_trade_id", "exchange", "market_type", "symbol", "quote", "unit"}

INT_COLUMNS = {"funding_cycle_ms"}

BOOL_COLUMNS = {"closed"}

COLUMNS: Dict[str, List[str]] = {
    "candles":          ["closed", "open", "high", "low", "close", "volume", "volume_notional"],
    "trades":           ["price", "qty", "qty_notional", "side", "id"],
    "agg_trades":       ["price", "qty", "qty_notional", "side", "agg_id", "first_trade_id", "last_trade_id"],
    "funding_rate":     ["funding_per_cycle", "funding_cycle_ms", "funding_per_hour"],
    "open_interest":    ["open_interest", "open_interest_notional"],
    "liquidations":     ["price", "qty", "qty_notional", "side"],
    "long_short_ratio": ["ratio", "long_account", "short_account"],
    "margin_tiers":     ["up_to", "max_leverage", "maintenance_margin_rate", "initial_margin_rate", "maintenance_deduction"],
}

ATTRS: Dict[str, List[str]] = {
    "candles":          ["quote", "interval", "volume_unit", "contract_size", "notional_basis"],
    "trades":           ["quote", "qty_unit", "contract_size"],
    "agg_trades":       ["quote", "qty_unit", "contract_size"],
    "funding_rate":     ["quote", "funding_kind"],
    "open_interest":    ["quote", "interval", "oi_unit", "open_interest_unit", "contract_size", "notional_basis"],
    "liquidations":     ["quote", "qty_unit", "contract_size"],
    "long_short_ratio": ["interval", "account_scope"],
}


def _base_attrs(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "exchange":       ctx["exchange"],
        "market_type":    ctx["market_type"],
        "symbol":         ctx["symbol"],
        "schema_version": SCHEMA_VERSION,
        "warnings":       [],
    }


def _indexed(rows: List[Dict]) -> pd.DataFrame:
    df = pd.json_normalize(rows, sep="_")
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").sort_index()

    return df


def _const(df: pd.DataFrame, column: str) -> Any:
    if column not in df.columns:
        return None

    series = df[column].dropna()
    if series.empty:
        return None

    return series.iloc[0]


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        if column in TEXT_COLUMNS or column in BOOL_COLUMNS:
            continue
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def _finalize(df: pd.DataFrame, attrs: Dict[str, Any], columns: List[str], warnings: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    out = df.reindex(columns=columns).copy()
    out = _coerce(out)

    attrs["warnings"] = warnings
    out.attrs.update(attrs)

    return out, warnings


def _empty(ctx: Dict[str, Any], route: str) -> Tuple[pd.DataFrame, List[str]]:
    message = f"0 rows returned for {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']} {route}"

    index = pd.DatetimeIndex([], tz="UTC", name="datetime")
    df    = pd.DataFrame({column: pd.Series(index=index, dtype=object if column in TEXT_COLUMNS else "int64" if column in INT_COLUMNS else "bool" if column in BOOL_COLUMNS else "float64") for column in COLUMNS[route]}, index=index)
    attrs = _base_attrs(ctx)
    attrs.update(dict.fromkeys(ATTRS[route]))
    attrs["warnings"] = [message]
    df.attrs.update(attrs)

    return df, [message]


def _quote_warning(quote: Optional[str], ctx: Dict[str, Any], route: str) -> Optional[str]:
    if quote and quote not in USD_FAMILY:
        return f"{route} {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: quote='{quote}'; *_notional fields are quote-denominated ({quote}), not US dollars"

    return None


def _short_result_warning(df: pd.DataFrame, ctx: Dict[str, Any], route: str) -> Optional[str]:
    requested = ctx.get("requested")
    if not ctx.get("paginated") or requested is None:
        return None

    if 0 < len(df) < requested:
        return f"{route} {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: got {len(df)} of {requested} requested; {ctx['exchange']} holds nothing older"

    return None


def _candles(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)
    df = df.rename(columns={"volume_native": "volume"})

    attrs = _base_attrs(ctx)
    attrs["quote"]          = _const(df, "quote")
    attrs["interval"]       = _const(df, "interval")
    attrs["volume_unit"]    = _const(df, "volume_unit")
    attrs["contract_size"]  = _const(df, "volume_contract_size")
    attrs["notional_basis"] = _const(df, "volume_notional_basis_method")

    warnings: List[str] = []
    short = _short_result_warning(df, ctx, "candles")
    if short:
        warnings.append(short)
    quote = _quote_warning(attrs["quote"], ctx, "candles")
    if quote:
        warnings.append(quote)

    return _finalize(df, attrs, COLUMNS["candles"], warnings)


def _trades(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)
    df = df.rename(columns={"qty_native": "qty"})

    attrs = _base_attrs(ctx)
    attrs["quote"]         = _const(df, "quote")
    attrs["qty_unit"]      = _const(df, "qty_unit")
    attrs["contract_size"] = _const(df, "qty_contract_size")

    warnings: List[str] = []
    if "id" in df.columns:
        missing = int(df["id"].isna().sum())
        if missing:
            warnings.append(f"trades {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: {missing} of {len(df)} trades have id=null; sort by timestamp, not id")
    quote = _quote_warning(attrs["quote"], ctx, "trades")
    if quote:
        warnings.append(quote)

    return _finalize(df, attrs, COLUMNS["trades"], warnings)


def _agg_trades(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)
    df = df.rename(columns={"qty_native": "qty"})

    attrs = _base_attrs(ctx)
    attrs["quote"]         = _const(df, "quote")
    attrs["qty_unit"]      = _const(df, "qty_unit")
    attrs["contract_size"] = _const(df, "qty_contract_size")

    warnings: List[str] = []
    short = _short_result_warning(df, ctx, "agg_trades")
    if short:
        warnings.append(short)
    quote = _quote_warning(attrs["quote"], ctx, "agg_trades")
    if quote:
        warnings.append(quote)

    return _finalize(df, attrs, COLUMNS["agg_trades"], warnings)


def _funding_rate(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)

    cycle_hours = df["funding_cycle_ms"] / 3_600_000
    df["funding_per_hour"] = df["funding_per_cycle"].where(cycle_hours == 0, df["funding_per_cycle"] / cycle_hours)

    attrs = _base_attrs(ctx)
    attrs["quote"]        = _const(df, "quote")
    attrs["funding_kind"] = _const(df, "funding_kind")

    warnings: List[str] = []
    if df["funding_cycle_ms"].nunique(dropna=True) > 1:
        warnings.append(f"funding_rate {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: funding cycle changed within the window; funding_per_hour is per-row correct")
    short = _short_result_warning(df, ctx, "funding_rate")
    if short:
        warnings.append(short)

    return _finalize(df, attrs, COLUMNS["funding_rate"], warnings)


def _open_interest(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)
    df = df.rename(columns={"open_interest_native": "open_interest"})

    attrs = _base_attrs(ctx)
    attrs["quote"]              = _const(df, "quote")
    attrs["interval"]           = _const(df, "interval")
    attrs["oi_unit"]            = _const(df, "open_interest_unit")
    attrs["open_interest_unit"] = attrs["oi_unit"]
    attrs["contract_size"]      = _const(df, "open_interest_contract_size")
    attrs["notional_basis"]     = _const(df, "open_interest_notional_basis_method")

    warnings: List[str] = []
    if "open_interest_notional" in df.columns:
        missing = int(df["open_interest_notional"].isna().sum())
        if missing:
            warnings.append(f"open_interest {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: {missing} of {len(df)} rows have notional=NaN (join missed; native is populated)")
    short = _short_result_warning(df, ctx, "open_interest")
    if short:
        warnings.append(short)
    quote = _quote_warning(attrs["quote"], ctx, "open_interest")
    if quote:
        warnings.append(quote)

    return _finalize(df, attrs, COLUMNS["open_interest"], warnings)


def _liquidations(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)
    df = df.rename(columns={"qty_native": "qty"})

    attrs = _base_attrs(ctx)
    attrs["quote"]         = _const(df, "quote")
    attrs["qty_unit"]      = _const(df, "qty_unit")
    attrs["contract_size"] = _const(df, "qty_contract_size")

    warnings: List[str] = []
    quote = _quote_warning(attrs["quote"], ctx, "liquidations")
    if quote:
        warnings.append(quote)

    return _finalize(df, attrs, COLUMNS["liquidations"], warnings)


def _long_short_ratio(rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    df = _indexed(rows)

    attrs = _base_attrs(ctx)
    attrs["interval"]      = _const(df, "interval")
    attrs["account_scope"] = _const(df, "account_scope")

    warnings: List[str] = []
    if attrs["account_scope"] == "opaque":
        warnings.append(f"long_short_ratio {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']}: account breakdown unavailable (account_scope='opaque'); long_account/short_account are NaN")
    short = _short_result_warning(df, ctx, "long_short_ratio")
    if short:
        warnings.append(short)

    return _finalize(df, attrs, COLUMNS["long_short_ratio"], warnings)


_BUILDERS = {
    "candles":          _candles,
    "trades":           _trades,
    "agg_trades":       _agg_trades,
    "funding_rate":     _funding_rate,
    "open_interest":    _open_interest,
    "liquidations":     _liquidations,
    "long_short_ratio": _long_short_ratio,
}


def build(route: str, rows: List[Dict], ctx: Dict[str, Any]) -> Tuple[pd.DataFrame, List[str]]:
    if not rows:
        return _empty(ctx, route)

    return _BUILDERS[route](rows, ctx)


def orderbook(data: Dict[str, Any], ctx: Dict[str, Any]) -> pd.DataFrame:
    bids = data.get("bids") or []
    asks = data.get("asks") or []

    records = [{"side": "bid", "price": p, "qty": q} for p, q in bids]
    records += [{"side": "ask", "price": p, "qty": q} for p, q in asks]

    df = pd.DataFrame(records, columns=["side", "price", "qty"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["qty"]   = pd.to_numeric(df["qty"], errors="coerce")

    qty = data.get("qty") or {}
    df.attrs.update({
        "exchange":          ctx["exchange"],
        "market_type":       ctx["market_type"],
        "symbol":            ctx["symbol"],
        "quote":             data.get("quote"),
        "qty_unit":          qty.get("unit"),
        "qty_contract_size": qty.get("contract_size"),
        "timestamp":         data.get("timestamp"),
        "time_source":       data.get("time_source"),
        "schema_version":    SCHEMA_VERSION,
        "warnings":          [],
    })

    return df


def margin_tiers(data: Dict[str, Any], ctx: Dict[str, Any]) -> pd.DataFrame:
    tiers    = data.get("tiers") or []
    warnings = [] if tiers else [f"0 tiers returned for {ctx['exchange']}/{ctx['market_type']}/{ctx['symbol']} margin_tiers"]

    df = _coerce(pd.DataFrame(tiers, columns=COLUMNS["margin_tiers"]))

    df.attrs.update({
        "exchange":       ctx["exchange"],
        "market_type":    ctx["market_type"],
        "symbol":         ctx["symbol"],
        "quote":          data.get("quote"),
        "up_to_unit":     data.get("up_to_unit"),
        "timestamp":      data.get("timestamp"),
        "schema_version": SCHEMA_VERSION,
        "warnings":       warnings,
    })

    return df


def with_provenance(df: pd.DataFrame) -> pd.DataFrame:
    attrs = dict(df.attrs)
    out   = df.copy()

    out["exchange"]    = attrs.get("exchange")
    out["market_type"] = attrs.get("market_type")
    out["symbol"]      = attrs.get("symbol")
    out["quote"]       = attrs.get("quote")
    out["unit"]        = attrs.get("volume_unit") or attrs.get("qty_unit") or attrs.get("oi_unit") or attrs.get("up_to_unit")

    out.attrs.update(attrs)

    return out
