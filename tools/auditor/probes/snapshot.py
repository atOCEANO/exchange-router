import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from tools.auditor.config import DEADLINES, MID_PRICED, ROUTER_STAMPED, SNAPSHOT_FRESHNESS_MS
from tools.auditor.aggregator import ErrorType, ProbeResult

from tools.auditor.probes.base import (
    Probe, ProbeContext, dig, fetch, now_ms, validate_one, venue_fetch,
)


def _age(d: dict, ctx: ProbeContext, route: str) -> Optional[Tuple[str, ErrorType, str, Dict[str, Any]]]:
    if (ctx.exchange, ctx.market_type, route) in ROUTER_STAMPED:
        return None
    age_ms = now_ms() - d["timestamp"]
    if age_ms > SNAPSHOT_FRESHNESS_MS:
        return "warn", ErrorType.LOGIC, f"stale: {age_ms/1000:.0f}s old", {"age_ms": age_ms, "timestamp": d["timestamp"]}
    return None


def _ticker_checks(d: dict, ctx: ProbeContext) -> Tuple[str, ErrorType, str, Dict[str, Any]]:
    price     = d["price"]
    low, high = d["low_24h"], d["high_24h"]
    vol_obj   = d.get("volume_24h") or {}
    vol_native = vol_obj.get("native", 0) if isinstance(vol_obj, dict) else 0
    if price < 0:
        return "fail", ErrorType.LOGIC, f"negative price {price}", {"price": price}
    if price == 0:
        return "warn", ErrorType.LOGIC, "no last trade (price 0.0)", {"price": price}
    if ctx.exchange not in MID_PRICED and high > 0 and low > 0 and not (low <= price <= high):
        return "warn", ErrorType.LOGIC, f"price {price} outside 24h range [{low}, {high}]", {"price": price, "low": low, "high": high}
    if vol_native < 0:
        return "fail", ErrorType.LOGIC, f"negative volume {vol_native}", {"volume": vol_native}
    stale = _age(d, ctx, "ticker")
    if stale:
        return stale
    return "pass", ErrorType.OK, f"price={price}, vol24h={vol_native:.4g}", {"price": price}


def _book_ticker_checks(d: dict, ctx: ProbeContext) -> Tuple[str, ErrorType, str, Dict[str, Any]]:
    bid, ask = d["bid_price"], d["ask_price"]
    bid_qty_obj = d.get("bid_qty") or {}
    ask_qty_obj = d.get("ask_qty") or {}
    bid_qty = bid_qty_obj.get("native", 0) if isinstance(bid_qty_obj, dict) else 0
    ask_qty = ask_qty_obj.get("native", 0) if isinstance(ask_qty_obj, dict) else 0
    empty = [side for side, price in (("bid", bid), ("ask", ask)) if price is None]
    if empty:
        return "warn", ErrorType.LOGIC, f"{' and '.join(empty)} side empty", {"bid": bid, "ask": ask}
    if bid < 0 or ask < 0:
        return "fail", ErrorType.LOGIC, f"negative price: bid={bid}, ask={ask}", {"bid": bid, "ask": ask}
    if bid > ask:
        return "fail", ErrorType.LOGIC, f"crossed book: bid {bid} > ask {ask}", {"bid": bid, "ask": ask}
    if bid_qty <= 0 or ask_qty <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive qty: bid_qty={bid_qty}, ask_qty={ask_qty}", {"bid_qty": bid_qty, "ask_qty": ask_qty}
    stale = _age(d, ctx, "book_ticker")
    if stale:
        return stale
    spread = ask - bid
    return "pass", ErrorType.OK, f"bid={bid}, ask={ask}, spread={spread:.6g}", {"bid": bid, "ask": ask, "spread": spread}


def _mark_price_checks(d: dict, ctx: ProbeContext) -> Tuple[str, ErrorType, str, Dict[str, Any]]:
    mp = d["mark_price"]
    ip = d.get("index_price")
    funding_obj = d.get("funding")
    fr = funding_obj.get("per_cycle") if isinstance(funding_obj, dict) else None
    if mp <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive mark={mp}", {"mark": mp}
    if ip is not None and ip <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive index={ip}", {"index": ip}
    stale = _age(d, ctx, "mark_price")
    if stale:
        return stale
    return "pass", ErrorType.OK, f"mark={mp}, index={ip}, fr={fr}", {"mark": mp, "index": ip, "funding_rate": fr}


def deadline_verdict(router_ts: int, venue_ts: Optional[int], cycle_ms: int) -> str:
    if venue_ts is None:
        return "skip"
    if abs(router_ts - venue_ts) <= 1000:
        return "pass"
    if abs(abs(router_ts - venue_ts) - cycle_ms) <= 1000:
        return "settled"
    return "fail"


SNAPSHOT_CHECKS: Dict[str, Callable[[dict, ProbeContext], Tuple[str, ErrorType, str, Dict[str, Any]]]] = {
    "ticker":      _ticker_checks,
    "book_ticker": _book_ticker_checks,
    "mark_price":  _mark_price_checks,
}


class SnapshotProbe(Probe):
    kind = "rest"


    def __init__(self, route: str, model: Type[BaseModel]):
        self.route = route
        self.name  = route
        self.model = model
        self.checks = SNAPSHOT_CHECKS.get(route)


    def applies(self, ctx: ProbeContext) -> bool:
        return bool(ctx.caps_slice and ctx.caps_slice.get(self.route, {}).get("rest"))


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        endpoint = f"/{ctx.exchange}/{ctx.market_type}/{self.route}/{ctx.symbol}"
        started = time.time()
        status, data, err = await fetch(ctx.client, endpoint)

        if status != 200:
            return [self.http_failure(ctx, self.name, started, status, data, err)]

        shape_err = validate_one(data, self.model)
        if shape_err:
            msg, ev = shape_err
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message=msg,
                evidence=ev,
            )]

        if self.checks is None:
            r = self.result(
                ctx, self.name, started,
                status="pass",
                error_type=ErrorType.OK,
                message="parsed OK",
            )
            r.sample = data
            return [r]

        s, et, msg, ev = self.checks(data, ctx)
        r = self.result(
            ctx, self.name, started,
            status=s,
            error_type=et,
            message=msg,
            evidence=ev,
        )
        r.sample = data

        if self.route == "mark_price":
            return [r, await self._deadline(ctx, data)]
        return [r]


    async def _deadline(self, ctx: ProbeContext, data: dict) -> ProbeResult:
        name    = f"{self.name}:deadline"
        started = time.time()
        table   = DEADLINES.get((ctx.exchange, ctx.market_type))
        funding = data.get("funding") or {}
        if table is None or not (funding.get("valid_until") or {}).get("ts"):
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message="no venue deadline to compare")

        _, info, _ = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/markets/{ctx.symbol}")
        native     = info.get("native_symbol") if isinstance(info, dict) else None
        url, params, path = table
        router_ts  = funding["valid_until"]["ts"]
        venue_ts   = dig(await venue_fetch(ctx.client, url, {k: v.format(native=native) for k, v in params.items()}), path)
        venue_ts   = int(venue_ts) if venue_ts not in (None, "") else None
        verdict    = deadline_verdict(router_ts, venue_ts, funding.get("cycle_ms") or 0)

        if verdict == "settled":
            _, again, _ = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/{self.route}/{ctx.symbol}")
            router_ts   = (((again or {}).get("funding") or {}).get("valid_until") or {}).get("ts") or router_ts
            verdict     = "pass" if abs(router_ts - venue_ts) <= 1000 else "fail"

        evidence = {"router_valid_until_ts": router_ts, "venue_next_settlement": venue_ts, "native_symbol": native}
        if verdict == "skip":
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message="the venue sent no deadline", evidence=evidence)
        if verdict == "fail":
            return self.result(ctx, name, started, status="fail", error_type=ErrorType.LOGIC, message=f"funding deadline {router_ts} is not the venue's next settlement {venue_ts}", evidence=evidence)
        return self.result(ctx, name, started, status="pass", error_type=ErrorType.OK, message="funding deadline is the venue's next settlement", evidence=evidence)
