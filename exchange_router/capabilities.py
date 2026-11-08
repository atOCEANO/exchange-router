from typing import Any, Dict, Optional


KNOWN_WS_CHANNELS = {"ticker", "book_ticker", "mark_price", "agg_trades", "trades", "orderbook", "liquidations"}


def market_block(capabilities: Optional[Dict[str, Any]], market_type: Any) -> Dict[str, Any]:
    markets = (capabilities or {}).get("market_types") or {}

    return markets.get(market_type) or markets.get(getattr(market_type, "value", market_type)) or {}


def route_block(capabilities: Optional[Dict[str, Any]], market_type: Any, route: str) -> Dict[str, Any]:
    return market_block(capabilities, market_type).get(route) or {}
