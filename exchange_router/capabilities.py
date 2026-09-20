from typing import Any, Dict, Optional


def market_block(capabilities: Optional[Dict[str, Any]], market_type: Any) -> Dict[str, Any]:
    markets = (capabilities or {}).get("markets") or {}

    return markets.get(market_type) or markets.get(getattr(market_type, "value", market_type)) or {}


def route_block(capabilities: Optional[Dict[str, Any]], market_type: Any, route: str) -> Dict[str, Any]:
    return market_block(capabilities, market_type).get(route) or {}
