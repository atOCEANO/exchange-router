import dataclasses
import time
from typing import Any, Dict, List

from tools.auditor.aggregator import ErrorType, ProbeResult
from tools.auditor.config import SAMPLE_MAX_ITEMS

from tools.auditor.probes.base import Probe, ProbeContext, fetch, unknown_kind


class MarketsProbe(Probe):
    kind  = "rest"
    route = "markets"
    name  = "markets"


    def applies(self, ctx: ProbeContext) -> bool:
        return ctx.market_type is not None


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        endpoint = f"/{ctx.exchange}/{ctx.market_type}/markets"
        started = time.time()
        status, body, err = await fetch(ctx.client, endpoint)

        if status != 200:
            return [self.http_failure(ctx, self.name, started, status, body, err)]
        if not isinstance(body, dict) or "markets" not in body:
            return [self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.SCHEMA,
                message="response is not the lite-list shape",
                evidence={"got_type": type(body).__name__, "keys": list(body.keys()) if isinstance(body, dict) else None},
            )]

        entries = body["markets"]
        bad: List[str]  = []
        seen: set        = set()
        dups: List[str]  = []
        for entry in entries:
            if not isinstance(entry, dict) or "symbol" not in entry:
                bad.append(repr(entry))
                continue
            s = entry["symbol"]
            if not isinstance(s, str) or not s:
                bad.append(repr(s))
                continue
            if "/" in s or s != s.upper():
                bad.append(s)
            if s in seen:
                dups.append(s)
            else:
                seen.add(s)

            for required_key in ("status", "base", "quote", "qty", "funding"):
                if required_key not in entry:
                    bad.append(f"{s}: missing {required_key}")
                    break

        data   = entries
        sample = data[:SAMPLE_MAX_ITEMS]

        if bad:
            r = self.result(
                ctx, self.name, started,
                status="warn",
                error_type=ErrorType.LOGIC,
                message=f"{len(data)} symbols, {len(bad)} formatting issues",
                evidence={"count": len(data), "bad_sample": bad[:5]},
            )
            r.sample = sample
            return [r]
        if dups:
            r = self.result(
                ctx, self.name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message=f"{len(dups)} duplicate symbols",
                evidence={"duplicates": dups[:5]},
            )
            r.sample = sample
            return [r]

        kind = unknown_kind(entries)
        if kind:
            r = self.result(
                ctx, self.name, started,
                status=kind[0],
                error_type=kind[1],
                message=kind[2],
                evidence=kind[3],
            )
            r.sample = sample
            return [r]

        r = self.result(
            ctx, self.name, started,
            status="pass",
            error_type=ErrorType.OK,
            message=f"{len(data)} symbols",
            evidence={"count": len(data)},
        )
        r.sample = sample
        return [r]


LIMITED = ("trades", "agg_trades", "candles", "funding_rate", "open_interest", "liquidations", "long_short_ratio")


class HaltedMarketProbe(Probe):
    kind  = "rest"
    route = "markets"
    name  = "markets:halted"


    def applies(self, ctx: ProbeContext) -> bool:
        return ctx.market_type is not None


    async def run(self, ctx: ProbeContext) -> List[ProbeResult]:
        started = time.time()
        status, body, err = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/markets", {"status": "halted"})

        if status != 200:
            return [self.http_failure(ctx, self.name, started, status, body, err)]
        entries = body.get("markets") if isinstance(body, dict) else None
        if not entries:
            return [self.result(ctx, self.name, started, status="skip", error_type=ErrorType.SKIPPED, message="no halted market listed")]

        halted = dataclasses.replace(ctx, symbol=entries[0]["symbol"])
        out    = [await self._symbol_info(halted)]
        for route, block in (ctx.caps_slice or {}).items():
            if isinstance(block, dict) and block.get("rest"):
                out.append(await self._answers(halted, route, block))
        return out


    async def _symbol_info(self, ctx: ProbeContext) -> ProbeResult:
        name    = f"{self.name}:symbol_info"
        started = time.time()
        status, info, err = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/markets/{ctx.symbol}")

        if status != 200:
            return self.http_failure(ctx, name, started, status, info, err)
        said = (info.get("status"), info.get("time_source"))
        if said != ("halted", "router") or not info.get("timestamp"):
            return self.result(
                ctx, name, started,
                status="fail",
                error_type=ErrorType.LOGIC,
                message=f"a halted market's symbol info says {said}, read at {info.get('timestamp')}",
                evidence={"status": said[0], "time_source": said[1], "timestamp": info.get("timestamp")},
            )
        return self.result(
            ctx, name, started,
            status="pass",
            error_type=ErrorType.OK,
            message=f"{ctx.symbol} says halted, read at {info['timestamp']}",
            evidence={"timestamp": info["timestamp"]},
        )


    async def _answers(self, ctx: ProbeContext, route: str, block: Dict[str, Any]) -> ProbeResult:
        name    = f"{self.name}:{route}"
        started = time.time()
        params: Dict[str, Any] = {"limit": 5} if route in LIMITED else {}
        if block.get("intervals"):
            params["interval"] = block["intervals"][0]
        status, data, err = await fetch(ctx.client, f"/{ctx.exchange}/{ctx.market_type}/{route}/{ctx.symbol}", params)

        if status != 200:
            return self.http_failure(ctx, name, started, status, data, err)
        return self.result(
            ctx, name, started,
            status="pass",
            error_type=ErrorType.OK,
            message=f"{ctx.symbol} is halted and {route} answers",
            evidence={"params": params},
        )
