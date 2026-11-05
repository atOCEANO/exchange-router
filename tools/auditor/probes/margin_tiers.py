import time
from typing import Any, Dict, List, Optional, Tuple

from exchange_router.models import MarginTiers
from tools.auditor.aggregator import ErrorType, ProbeResult

from tools.auditor.probes.base import Probe, ProbeContext, fetch, validate_one


def _table_fault(tiers: List[Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    bounds = [tier["up_to"] for tier in tiers]
    closed = [bound for bound in bounds if bound is not None]

    if None in bounds[:-1]:
        return "an open tier before the last", {"up_to": bounds}
    if any(later <= earlier for earlier, later in zip(closed, closed[1:])):
        return "up_to does not rise from tier to tier", {"up_to": bounds}

    for i, tier in enumerate(tiers):
        if tier["max_leverage"] <= 0:
            return f"non-positive max_leverage at tier {i}", {"tier": i, "max_leverage": tier["max_leverage"]}
        for field in ("maintenance_margin_rate", "initial_margin_rate"):
            rate = tier.get(field)
            if rate is not None and not 0 < rate <= 1:
                return f"{field} {rate} at tier {i} is outside (0, 1]", {"tier": i, field: rate}
    return None


def _table_oddity(tiers: List[Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    leverage = [tier["max_leverage"] for tier in tiers]

    if any(later > earlier for earlier, later in zip(leverage, leverage[1:])):
        return "max_leverage rises from one tier to the next", {"max_leverage": leverage}

    for i, tier in enumerate(tiers):
        mmr = tier.get("maintenance_margin_rate")
        imr = tier.get("initial_margin_rate")
        if mmr is not None and imr is not None and mmr > imr:
            return f"maintenance rate {mmr} above the initial rate {imr} at tier {i}", {"tier": i, "mmr": mmr, "imr": imr}
    return None


class MarginTiersProbe(Probe):
    kind  = "rest"
    route = "margin_tiers"
    name  = "margin_tiers"


    def applies(self, ctx: ProbeContext) -> bool:
        return bool(ctx.caps_slice and ctx.caps_slice.get("margin_tiers", {}).get("rest"))


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        endpoint = f"/{ctx.exchange}/{ctx.market_type}/margin_tiers/{ctx.symbol}"
        started  = time.time()
        status, data, err = await fetch(ctx.client, endpoint)

        if status != 200:
            return [self.http_failure(ctx, self.name, started, status, data, err)]

        shape_err = validate_one(data, MarginTiers)
        if shape_err:
            msg, ev = shape_err
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message=msg,
                evidence=ev,
            )]

        tiers = data["tiers"]
        if not tiers:
            return [self.result(
                ctx, self.name, started,
                status="warn",
                error_type=ErrorType.EMPTY,
                message="no tiers served for the probe symbol",
                evidence={"symbol": ctx.symbol},
            )]

        fault = _table_fault(tiers)
        if fault:
            msg, ev = fault
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message=msg,
                evidence=ev,
            )]

        oddity = _table_oddity(tiers)
        if oddity:
            msg, ev = oddity
            return [self.result(
                ctx, self.name, started,
                status="warn",
                error_type=ErrorType.LOGIC,
                message=msg,
                evidence=ev,
            )]

        r = self.result(
            ctx, self.name, started,
            status="pass",
            error_type=ErrorType.OK,
            message=f"{len(tiers)} tiers in {data['up_to_unit']}",
            evidence={"tiers": len(tiers), "up_to_unit": data["up_to_unit"]},
        )
        r.sample = data
        return [r]
