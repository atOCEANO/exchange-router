from typing import Any, Dict, Optional


class Row(dict):

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


    @property
    def raw(self) -> Optional[dict]:
        return getattr(self, "_raw", None)


def _qty(obj: Any):
    if not isinstance(obj, dict):
        return None, None, None
    return obj.get("native"), obj.get("notional"), obj.get("unit")


def _wrap(flat: Dict[str, Any], raw: Dict[str, Any]) -> Row:
    row = Row(flat)
    row._raw = raw
    return row


def ticker_row(raw: Dict[str, Any]) -> Row:
    native, notional, unit = _qty(raw.get("volume_24h"))

    flat = {
        "symbol":               raw.get("symbol"),
        "market_type":          raw.get("market_type"),
        "quote":                raw.get("quote"),
        "price":                raw.get("price"),
        "open_24h":             raw.get("open_24h"),
        "high_24h":             raw.get("high_24h"),
        "low_24h":              raw.get("low_24h"),
        "volume_24h":           native,
        "volume_24h_notional":  notional,
        "volume_24h_unit":      unit,
        "price_change_percent": raw.get("price_change_percent"),
        "timestamp":            raw.get("timestamp"),
    }

    return _wrap(flat, raw)


def book_ticker_row(raw: Dict[str, Any]) -> Row:
    bid_native, bid_notional, bid_unit = _qty(raw.get("bid_qty"))
    ask_native, ask_notional, ask_unit = _qty(raw.get("ask_qty"))

    flat = {
        "symbol":           raw.get("symbol"),
        "market_type":      raw.get("market_type"),
        "quote":            raw.get("quote"),
        "bid_price":        raw.get("bid_price"),
        "bid_qty":          bid_native,
        "bid_qty_notional": bid_notional,
        "ask_price":        raw.get("ask_price"),
        "ask_qty":          ask_native,
        "ask_qty_notional": ask_notional,
        "qty_unit":         bid_unit or ask_unit,
        "timestamp":        raw.get("timestamp"),
        "time_source":      raw.get("time_source"),
    }

    return _wrap(flat, raw)


def mark_price_row(raw: Dict[str, Any]) -> Row:
    funding   = raw.get("funding") or {}
    deadline  = funding.get("valid_until") or {}
    per_cycle = funding.get("per_cycle")
    cycle_ms  = funding.get("cycle_ms")

    if per_cycle is not None and cycle_ms:
        per_hour = per_cycle / (cycle_ms / 3_600_000)
    else:
        per_hour = None

    flat = {
        "symbol":                   raw.get("symbol"),
        "market_type":              raw.get("market_type"),
        "quote":                    raw.get("quote"),
        "mark_price":               raw.get("mark_price"),
        "index_price":              raw.get("index_price"),
        "funding_kind":             funding.get("kind"),
        "funding_per_cycle":        per_cycle,
        "funding_cycle_ms":         cycle_ms,
        "funding_per_hour":         per_hour,
        "funding_valid_until_ts":   deadline.get("ts"),
        "funding_valid_until_kind": deadline.get("kind"),
        "timestamp":                raw.get("timestamp"),
        "time_source":              raw.get("time_source"),
    }

    return _wrap(flat, raw)


def symbol_info_row(raw: Dict[str, Any]) -> Row:
    price    = raw.get("price") or {}
    qty      = raw.get("qty") or {}
    notional = raw.get("notional") or {}
    funding  = raw.get("funding") or {}

    flat = {
        "symbol":            raw.get("symbol"),
        "market_type":       raw.get("market_type"),
        "native_symbol":     raw.get("native_symbol"),
        "status":            raw.get("status"),
        "base":              raw.get("base"),
        "quote":             raw.get("quote"),
        "price_kind":        price.get("kind"),
        "price_tick":        price.get("tick"),
        "price_figures":     price.get("figures"),
        "price_decimals":    price.get("decimals"),
        "qty_unit":          qty.get("unit"),
        "qty_contract_size": qty.get("contract_size"),
        "qty_step":          qty.get("step"),
        "qty_decimals":      qty.get("decimals"),
        "qty_min":           qty.get("min"),
        "qty_max":           qty.get("max"),
        "notional_min":      notional.get("min"),
        "funding_kind":      funding.get("kind"),
        "timestamp":         raw.get("timestamp"),
        "time_source":       raw.get("time_source"),
    }

    return _wrap(flat, raw)
