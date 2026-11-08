import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from tools.auditor.config import DEADLINES, PRICE_SLACK, PRICES
from tools.auditor.aggregator import ErrorType, ProbeResult

from tools.auditor.probes.base import (
    Probe, ProbeContext, dig, fetch, fill, judge_time, native_symbol, now_ms, unknown_kind, validate_one,
    venue_fetch, venue_record,
)


def _ticker_checks(d: dict, ctx: ProbeContext) -> Tuple[str, ErrorType, str, Dict[str, Any]]:
    price     = d["price"]
    low, high = d["low_24h"], d["high_24h"]
    vol_obj   = d.get("volume_24h") or {}
    vol_native = vol_obj.get("native", 0) if isinstance(vol_obj, dict) else 0
    if price is None:
        return "skip", ErrorType.SKIPPED, "no last trade (price null)", {"price": price}
    if price <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive price {price}", {"price": price}
    if d.get("price_source") == "last_trade" and high and low and not (low <= price <= high):
        return "warn", ErrorType.LOGIC, f"price {price} outside 24h range [{low}, {high}]", {"price": price, "low": low, "high": high}
    if vol_native < 0:
        return "fail", ErrorType.LOGIC, f"negative volume {vol_native}", {"volume": vol_native}
    return "pass", ErrorType.OK, f"price={price}, vol24h={vol_native:.4g}", {"price": price}


def _book_ticker_checks(d: dict, ctx: ProbeContext) -> Tuple[str, ErrorType, str, Dict[str, Any]]:
    bid, ask = d["bid_price"], d["ask_price"]
    bid_qty_obj = d.get("bid_qty") or {}
    ask_qty_obj = d.get("ask_qty") or {}
    bid_qty = bid_qty_obj.get("native", 0) if isinstance(bid_qty_obj, dict) else 0
    ask_qty = ask_qty_obj.get("native", 0) if isinstance(ask_qty_obj, dict) else 0
    empty = [side for side, price in (("bid", bid), ("ask", ask)) if price is None]
    if empty:
        return "skip", ErrorType.SKIPPED, f"{' and '.join(empty)} side empty; no spread to check", {"bid": bid, "ask": ask}
    if bid <= 0 or ask <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive price: bid={bid}, ask={ask}", {"bid": bid, "ask": ask}
    if bid > ask:
        return "fail", ErrorType.LOGIC, f"crossed book: bid {bid} > ask {ask}", {"bid": bid, "ask": ask}
    if bid_qty <= 0 or ask_qty <= 0:
        return "fail", ErrorType.LOGIC, f"non-positive qty: bid_qty={bid_qty}, ask_qty={ask_qty}", {"bid_qty": bid_qty, "ask_qty": ask_qty}
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
    return "pass", ErrorType.OK, f"mark={mp}, index={ip}, fr={fr}", {"mark": mp, "index": ip, "funding_rate": fr}


def deadline_verdict(router_ts: int, venue_ts: Optional[int], cycle_ms: int) -> str:
    if venue_ts is None:
        return "skip"
    if abs(router_ts - venue_ts) <= 1000:
        return "pass"
    if abs(abs(router_ts - venue_ts) - cycle_ms) <= 1000:
        return "settled"
    return "fail"


def price_verdict(price: float, before: float, after: float) -> Optional[str]:
    low, high = min(before, after), max(before, after)
    if low * (1 - PRICE_SLACK) <= price <= high * (1 + PRICE_SLACK):
        return None
    return f"price {price} lies outside {low} to {high}, the venue's own reading either side of it"


def estimate_verdict(ts: int, cycle_ms: Optional[int], now: int) -> Optional[str]:
    if cycle_ms and abs(ts - now) <= cycle_ms:
        return None
    return f"the estimate lies {(ts - now)/1000:.0f}s from now, beyond one cycle of {(cycle_ms or 0)/1000:.0f}s"


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
        if s == "pass":
            s, et, msg, ev = unknown_kind(data) or await judge_time(ctx, self.route, data) or (s, et, msg, ev)
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
        if self.route == "ticker":
            return [r, await self._venue_price(ctx, data)]
        return [r]


    async def _venue_price(self, ctx: ProbeContext, data: dict) -> ProbeResult:
        name    = f"{self.name}:venue_price"
        started = time.time()
        entry   = PRICES.get((ctx.exchange, ctx.market_type, data.get("price_source")))
        if entry is None or data.get("price") is None:
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message=f"no venue reading of {data.get('price_source')} to compare")

        native      = await native_symbol(ctx)
        before      = dig(await venue_record(ctx.client, entry, native), fill(entry[2], native))
        _, again, _ = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/ticker/{ctx.symbol}")
        after       = dig(await venue_record(ctx.client, entry, native), fill(entry[2], native))
        price       = again.get("price") if isinstance(again, dict) else None
        evidence    = {"venue_before": before, "price": price, "venue_after": after, "price_source": data["price_source"], "native_symbol": native}

        if None in (before, price, after):
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message="the venue or the router sent no price to compare", evidence=evidence)
        problem = price_verdict(float(price), float(before), float(after))
        if problem:
            return self.result(ctx, name, started, status="fail", error_type=ErrorType.LOGIC, message=problem, evidence=evidence)
        return self.result(ctx, name, started, status="pass", error_type=ErrorType.OK, message=f"price lies within the venue's own {data['price_source']} read either side of it", evidence=evidence)


    async def _deadline(self, ctx: ProbeContext, data: dict) -> ProbeResult:
        name    = f"{self.name}:deadline"
        started = time.time()
        table   = DEADLINES.get((ctx.exchange, ctx.market_type))
        funding = data.get("funding") or {}
        until   = funding.get("valid_until") or {}
        if until.get("kind") == "estimate":
            problem  = estimate_verdict(until["ts"], funding.get("cycle_ms"), now_ms())
            evidence = {"valid_until": until, "cycle_ms": funding.get("cycle_ms")}
            if problem:
                return self.result(ctx, name, started, status="fail", error_type=ErrorType.LOGIC, message=problem, evidence=evidence)
            return self.result(ctx, name, started, status="pass", error_type=ErrorType.OK, message="the estimate lies within one cycle of now", evidence=evidence)
        if table is None or not until.get("ts"):
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
