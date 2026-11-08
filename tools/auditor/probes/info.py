import decimal
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from exchange_router.models import SymbolInfo
from tools.auditor.aggregator import ErrorType, ProbeResult
from tools.auditor.config import INSTRUMENTS

from tools.auditor.probes.base import Probe, ProbeContext, dig, fetch, fill, unknown_kind, validate_one, venue_record


def _decimals(value: float) -> int:
    exponent = decimal.Decimal(str(value)).normalize().as_tuple().exponent
    return max(-exponent, 0) if isinstance(exponent, int) else 0


def _grid_mismatch(data: Dict[str, Any]) -> Optional[Tuple[str, ErrorType, str, Dict[str, Any]]]:
    price = data["price"]
    qty   = data["qty"]

    if price.get("kind") == "tick" and _decimals(price["tick"]) != price["decimals"]:
        return (
            "warn", ErrorType.LOGIC,
            f"price.decimals {price['decimals']} does not match price.tick {price['tick']}",
            {"price": price},
        )
    if qty["step"] is not None and _decimals(qty["step"]) != qty["decimals"]:
        return (
            "warn", ErrorType.LOGIC,
            f"qty.decimals {qty['decimals']} does not match qty.step {qty['step']}",
            {"qty": qty},
        )
    return None


def venue_grid(record: Any, fields: Dict[str, List[Tuple]], native: Optional[str]) -> Dict[str, Optional[float]]:
    out = {}
    for field, paths in fields.items():
        values     = [dig(record, fill(path, native)) for path in paths]
        readable   = all(isinstance(value, (int, float, str)) and value != "" for value in values)
        out[field] = abs(math.prod(float(value) for value in values)) if readable else None
    return out


def instrument_findings(info: Dict[str, Any], venue: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    price, qty = info["price"], info["qty"]
    router     = {"tick": price.get("tick"), "step": qty["step"], "min": qty["min"], "max": qty["max"], "decimals": qty["decimals"], "contract_size": qty["contract_size"]}
    return [
        {"field": field, "router": router[field], "venue": value}
        for field, value in venue.items()
        if (router[field] is None) != (value is None) or (value is not None and not math.isclose(router[field], value, rel_tol=1e-9))
    ]


class InfoProbe(Probe):
    kind  = "rest"
    route = "markets"
    name  = "markets:detail"


    def applies(self, ctx: ProbeContext) -> bool:
        return ctx.market_type is not None and ctx.symbol is not None


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        endpoint = f"/{ctx.exchange}/{ctx.market_type}/markets/{ctx.symbol}"
        started = time.time()
        status, data, err = await fetch(ctx.client, endpoint)

        if status != 200:
            return [self.http_failure(ctx, self.name, started, status, data, err)]

        if not isinstance(data, dict):
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message="response is not a dict",
                evidence={"got_type": type(data).__name__},
            )]

        shape_err = validate_one(data, SymbolInfo)
        if shape_err:
            msg, ev = shape_err
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message=msg,
                evidence=ev,
            )]

        price = data["price"]
        qty   = data["qty"]
        if qty["min"] is not None and qty["max"] is not None and qty["min"] > qty["max"]:
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message=f"qty.min {qty['min']} > qty.max {qty['max']}",
                evidence={"qty": qty},
            )]
        if (price.get("decimals") is not None and price["decimals"] < 0) or (qty["decimals"] is not None and qty["decimals"] < 0):
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message="negative decimals",
                evidence={"price": price, "qty": qty},
            )]
        if (price.get("kind") == "tick" and price["tick"] <= 0) or (qty["step"] is not None and qty["step"] <= 0):
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message="non-positive price.tick or qty.step",
                evidence={"price": price, "qty": qty},
            )]

        unit          = qty["unit"]
        contract_size = qty["contract_size"]
        if ctx.market_type == "inverse":
            unit_ok = unit == "contract"
            cs_ok   = contract_size is not None and contract_size > 0
            rule    = "inverse requires qty.unit='contract' and a positive qty.contract_size"
        else:
            unit_ok = unit == "base"
            cs_ok   = contract_size is None
            rule    = f"{ctx.market_type} requires qty.unit='base' and qty.contract_size=null"
        if not unit_ok or not cs_ok:
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message=f"unit contract broken: qty.unit={unit!r}, qty.contract_size={contract_size}; {rule}",
                evidence={"qty": qty, "market_type": ctx.market_type},
            )]

        s, et, msg, ev = unknown_kind(data) or _grid_mismatch(data) or ("pass", ErrorType.OK, f"symbol {data.get('symbol')} info parsed OK", {"symbol": data.get("symbol")})
        r = self.result(
            ctx, self.name, started,
            status=s,
            error_type=et,
            message=msg,
            evidence=ev,
        )
        r.sample = [data]
        return [r, await self._venue_record(ctx, data)]


    async def _venue_record(self, ctx: ProbeContext, data: Dict[str, Any]) -> ProbeResult:
        name    = "markets:venue_record"
        started = time.time()
        entry   = INSTRUMENTS.get((ctx.exchange, ctx.market_type))
        if entry is None:
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message=f"no venue record wired for {ctx.exchange} {ctx.market_type}")

        native = data.get("native_symbol")
        venue  = venue_grid(await venue_record(ctx.client, entry, native), entry[2], native)
        if all(value is None for value in venue.values()):
            return self.result(ctx, name, started, status="skip", error_type=ErrorType.SKIPPED, message=f"{ctx.exchange}'s own record of {native} could not be read")

        findings = instrument_findings(data, venue)
        if findings:
            return self.result(ctx, name, started, status="fail", error_type=ErrorType.LOGIC, message=f"{', '.join(f['field'] for f in findings)} differ from {ctx.exchange}'s own record", evidence={"findings": findings, "native_symbol": native})
        return self.result(ctx, name, started, status="pass", error_type=ErrorType.OK, message=f"{', '.join(venue)} match {ctx.exchange}'s own record", evidence={"venue": venue, "native_symbol": native})
