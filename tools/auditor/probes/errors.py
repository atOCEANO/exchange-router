import time
from typing import Any, List, Optional, Tuple

from tools.auditor.aggregator import ErrorType, ProbeResult

from tools.auditor.probes.base import Probe, ProbeContext, fetch


def body_verdict(status: Optional[int], body: Any, want_status: int, want_title: str) -> Optional[str]:
    title = body.get("error") if isinstance(body, dict) else None
    if (status, title) != (want_status, want_title):
        return f"got {status} {title!r}, expected {want_status} {want_title!r}"
    if not isinstance(body.get("detail"), str) or not body["detail"]:
        return f"the {title} body carries no detail sentence"
    return None


class ErrorPathProbe(Probe):
    kind  = "rest"
    route = "error_paths"
    name  = "error_paths"


    def applies(self, ctx: ProbeContext) -> bool:
        return ctx.market_type is None


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        out: List[ProbeResult] = []

        cases: List[Tuple[str, str, int, str]] = [
            ("error:unknown_exchange", "/zzznotanexchange/capabilities",          404, "Not Found"),
            ("error:bad_market_type",  f"/{ctx.exchange}/notamarket/markets",      400, "Invalid Request"),
            ("error:bad_symbol",       f"/{ctx.exchange}/spot/ticker/ZZZNOTREAL",  400, "Unknown Symbol"),
        ]

        for probe_name, path, want_status, want_title in cases:
            started = time.time()
            status, data, err = await fetch(ctx.client, path)
            ended = time.time()
            if err is not None:
                r = self.result(
                    ctx, probe_name, started,
                    status="fail",
                    error_type=ErrorType.NETWORK,
                    message=err,
                    evidence={"endpoint": path},
                    ended=ended,
                )
                out.append(r)
                continue
            problem = body_verdict(status, data, want_status, want_title)
            r = self.result(
                ctx, probe_name, started,
                status="fail" if problem else "pass",
                error_type=ErrorType.LOGIC if problem else ErrorType.OK,
                message=problem or f"HTTP {status} {want_title}",
                evidence={"endpoint": path, "status": status, "expected": f"{want_status} {want_title}"},
                ended=ended,
            )
            r.sample = data
            out.append(r)

        return out
