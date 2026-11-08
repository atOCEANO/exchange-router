import asyncio
import decimal
import itertools
import logging
import math
import time
import orjson
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Set, Tuple, Union, AsyncGenerator, Callable, Awaitable, Iterable
from datetime import datetime, timezone
from exchange_router.capabilities import route_block
from exchange_router.models import (
    Ticker, BookTicker, MarkPrice, OrderBook, Candle, Trade, AggTrade,
    MarketType, SymbolInfo, FundingRate, OpenInterest, Liquidation, LongShortRatio,
    MarginTier, MarginTiers,
    QtyValue, VolumeValue, OiValue, NotionalBasis,
    FundingCurrent, FundingDeadline, FundingHistorical, FundingConvention,
    QtyUnit, QtyGrid, PriceTick, PriceSignificantFigures, Notional,
)


logger = logging.getLogger(__name__)


class AdapterError(Exception):
    pass


class UpstreamUnavailableError(AdapterError):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamDataError(AdapterError):
    pass


class SubscriptionRefused(AdapterError):
    pass


_request_ids = itertools.count(1)


def next_request_id() -> int:
    return next(_request_ids)


def venue_value(record: Dict[str, Any], key: str, what: str) -> Any:
    value = record.get(key)
    if value is None or value == "":
        raise UpstreamDataError(f"{what} arrived without {key}")
    return value


STATUSES = ("trading", "halted", "pre_trading", "delisted")


def build_qty_value(native: float, qty_unit: str, contract_size: Optional[float], price: float) -> QtyValue:
    if qty_unit == "contract":
        if contract_size is None:
            raise ValueError("build_qty_value: contract_size is required when qty_unit == 'contract'")
        notional = native * contract_size
    else:
        notional = native * price

    return QtyValue(
        native        = native,
        unit          = qty_unit,
        contract_size = contract_size if qty_unit == "contract" else None,
        notional      = notional,
    )


def build_qty_unit(unit: str, contract_size: Optional[float]) -> QtyUnit:
    return QtyUnit(
        unit          = unit,
        contract_size = contract_size if unit == "contract" else None,
    )


def build_volume_value(native: float, volume_unit: str, contract_size: Optional[float], close: float) -> VolumeValue:
    if volume_unit == "contract":
        if contract_size is None:
            raise ValueError("build_volume_value: contract_size is required when volume_unit == 'contract'")
        notional = native * contract_size
        basis    = NotionalBasis(method="contract_size", price=None, ts=None)
    else:
        notional = native * close
        basis    = NotionalBasis(method="row_price", price=None, ts=None)

    return VolumeValue(
        native         = native,
        unit           = volume_unit,
        contract_size  = contract_size if volume_unit == "contract" else None,
        notional       = notional,
        notional_basis = basis,
    )


def build_oi_value(native: float, oi_unit: str, contract_size: Optional[float], method: str = "candle_close", price: Optional[float] = None, price_ts: Optional[int] = None) -> OiValue:
    if oi_unit == "contract":
        if contract_size is None:
            raise ValueError("build_oi_value: contract_size is required when oi_unit == 'contract'")
        notional = native * contract_size
        basis    = NotionalBasis(method="contract_size", price=None, ts=None)
        return OiValue(
            native         = native,
            unit           = oi_unit,
            contract_size  = contract_size,
            notional       = notional,
            notional_basis = basis,
        )

    if price is not None and price_ts is not None:
        notional = native * price
        basis    = NotionalBasis(method=method, price=price, ts=price_ts)
    else:
        notional = None
        basis    = NotionalBasis(method=method, price=None, ts=None)

    return OiValue(
        native         = native,
        unit           = oi_unit,
        contract_size  = None,
        notional       = notional,
        notional_basis = basis,
    )


def build_funding_current(kind: str, per_cycle: float, cycle_ms: int, valid_until_ts: int, valid_until_kind: str) -> FundingCurrent:
    return FundingCurrent(
        kind        = kind,
        per_cycle   = per_cycle,
        cycle_ms    = cycle_ms,
        valid_until = FundingDeadline(kind=valid_until_kind, ts=valid_until_ts),
    )


def build_funding_historical(kind: str, per_cycle: float, cycle_ms: int) -> FundingHistorical:
    return FundingHistorical(
        kind      = kind,
        per_cycle = per_cycle,
        cycle_ms  = cycle_ms,
    )


def stamp_funding_cycles(rows: List[FundingRate], current_ms: Optional[int]) -> List[FundingRate]:
    rows = sorted(rows, key=lambda r: r.timestamp)
    gaps = [None] + [round((b.timestamp - a.timestamp) / 1000) * 1000 for a, b in zip(rows, rows[1:])]

    held: List[Optional[int]] = []
    for i, gap in enumerate(gaps):
        around = {gaps[i - 1] if i > 0 else None, gaps[i + 1] if i + 1 < len(gaps) else None}
        held.append(gap if gap is not None and (gap == current_ms or gap in around) else None)

    out: List[FundingRate] = []
    for i, row in enumerate(rows):
        cycle = held[i]
        for distance in range(1, len(rows)):
            if cycle is not None:
                break
            for j in (i + distance, i - distance):
                if 0 <= j < len(rows) and held[j] is not None:
                    cycle = held[j]
                    break
        cycle = cycle if cycle is not None else current_ms
        if cycle is None:
            raise ValueError(f"stamp_funding_cycles: the cycle of {row.symbol} at {row.timestamp} cannot be read from its neighbours and the venue states no current cycle")
        out.append(row.model_copy(update={"funding": row.funding.model_copy(update={"cycle_ms": cycle})}))
    return out


def build_funding_convention(kind: str) -> FundingConvention:
    return FundingConvention(kind=kind)


def build_step(*parts: Any) -> Optional[float]:
    try:
        step = decimal.Decimal(1)
        for part in parts:
            step *= decimal.Decimal(str(part))
        value = float(step)
    except (ArithmeticError, TypeError, ValueError):
        return None

    if not math.isfinite(value) or value <= 0:
        return None

    return value


def build_step_from_decimals(decimals: Any) -> Optional[float]:
    if isinstance(decimals, bool) or (isinstance(decimals, float) and not decimals.is_integer()):
        return None

    try:
        step = f"1e{-int(decimals)}"
    except (ArithmeticError, TypeError, ValueError):
        return None

    return build_step(step)


def count_decimals(value: Any) -> Optional[int]:
    try:
        exponent = decimal.Decimal(str(value)).normalize().as_tuple().exponent
    except (ArithmeticError, TypeError, ValueError):
        return None

    if not isinstance(exponent, int):
        return None

    return max(-exponent, 0)


def build_price_tick(tick: Any) -> Optional[PriceTick]:
    value = build_step(tick)
    if value is None:
        return None

    return PriceTick(
        kind     = "tick",
        tick     = value,
        decimals = count_decimals(tick),
    )


def build_price_figures(figures: int, decimals: int) -> PriceSignificantFigures:
    return PriceSignificantFigures(
        kind     = "significant_figures",
        figures  = figures,
        decimals = decimals,
    )


def build_qty_grid(unit: str, contract_size: Optional[float], step: Optional[float],
                   minimum: Optional[float], maximum: Optional[float]) -> QtyGrid:
    return QtyGrid(
        unit          = unit,
        contract_size = contract_size if unit == "contract" else None,
        step          = step,
        decimals      = count_decimals(step) if step is not None else None,
        min           = minimum,
        max           = maximum,
    )


def build_notional(minimum: Optional[float]) -> Notional:
    return Notional(min=minimum)


def _blank_as_none(value: Any) -> Any:
    return None if value is None or value == "" else value


def build_margin_tier(up_to: Any, max_leverage: Any, maintenance_margin_rate: Any = None,
                      initial_margin_rate: Any = None, maintenance_deduction: Any = None) -> MarginTier:
    return MarginTier(
        up_to                   = _blank_as_none(up_to),
        max_leverage            = max_leverage,
        maintenance_margin_rate = _blank_as_none(maintenance_margin_rate),
        initial_margin_rate     = _blank_as_none(initial_margin_rate),
        maintenance_deduction   = _blank_as_none(maintenance_deduction),
    )


def validate_interval(adapter, market_type: MarketType, route: str, label: str, value: str) -> None:
    intervals = route_block(adapter.get_capabilities(), market_type, route).get("intervals")

    if intervals and value not in intervals:
        raise ValueError(f"{label} '{value}' is not valid for {adapter.name} {market_type.value} {route}")


def symbol_info_to_lite(info: SymbolInfo) -> Dict[str, Any]:
    funding = None
    if info.funding is not None:
        funding = {"kind": info.funding.kind}

    return {
        "symbol":  info.symbol,
        "status":  info.status,
        "base":    info.base,
        "quote":   info.quote,
        "qty":     {"unit": info.qty.unit, "contract_size": info.qty.contract_size},
        "funding": funding,
    }


_PERIOD_MS = {
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}


def _period_to_ms(period: str) -> Optional[int]:
    if not period or len(period) < 2:
        return None
    scale = _PERIOD_MS.get(period[-1])
    if scale is None:
        return None
    try:
        count = int(period[:-1])
    except ValueError:
        return None
    return count * scale


def bar_closed(opened: int, interval: str) -> bool:
    if interval.endswith("M"):
        start  = datetime.fromtimestamp(opened / 1000, tz=timezone.utc)
        months = start.month - 1 + int(interval[:-1])
        end    = int(start.replace(year=start.year + months // 12, month=months % 12 + 1, day=1).timestamp() * 1000)
    else:
        step = _period_to_ms(interval)
        if step is None:
            raise ValueError(f"interval '{interval}' has no known length")
        end = opened + step
    return end <= int(time.time() * 1000)


async def join_open_interest_basis(adapter, market_type: MarketType, symbol: str, period: str,
                                   start_time: Optional[int], limit: int,
                                   oi_rows: List[OpenInterest]) -> List[OpenInterest]:
    if market_type != MarketType.LINEAR or not any(row.open_interest.notional_basis.method == "candle_close" for row in oi_rows):
        return oi_rows

    intervals = route_block(adapter.get_capabilities(), market_type, "candles").get("intervals")
    if intervals and period not in intervals:
        return oi_rows

    try:
        candles = await adapter.get_candles(market_type, symbol, period, start_time, limit + 1)
    except NotImplementedError:
        return oi_rows

    if len(candles) < 2:
        return oi_rows

    period_ms = _period_to_ms(period)
    if period_ms is None:
        period_ms = candles[1].timestamp - candles[0].timestamp
    close_by_close_ts = {c.timestamp + period_ms: c.close for c in candles[:-1]}

    joined = []
    for oi_row in oi_rows:
        matching_close = close_by_close_ts.get(oi_row.timestamp)
        if matching_close is None or oi_row.open_interest.notional_basis.method != "candle_close":
            joined.append(oi_row)
            continue

        oi_obj = oi_row.open_interest
        new_oi_value = build_oi_value(
            native        = oi_obj.native,
            oi_unit       = oi_obj.unit,
            contract_size = oi_obj.contract_size,
            price         = matching_close,
            price_ts      = oi_row.timestamp,
        )
        joined.append(oi_row.model_copy(update={"open_interest": new_oi_value}))

    return joined


class StreamHub:
    ANSWER_S = 30


    def __init__(self,
                 name: str,
                 connect: Callable[[], Awaitable[Any]],
                 subscribe_payload: Callable[[List[str]], Iterable[Any]],
                 unsubscribe_payload: Callable[[List[str]], Iterable[Any]],
                 route: Callable[[Any], Optional[str]],
                 keepalive_payload: Optional[Any] = None,
                 keepalive_interval: float = 0.0,
                 queue_size: int = 1024,
                 answer: Optional[Callable[[Any], Optional[Tuple[str, Optional[str]]]]] = None,
                 request_key: Optional[Callable[[Any], Optional[str]]] = None):
        self.name                = name
        self._connect            = connect
        self._sub_payload        = subscribe_payload
        self._unsub_payload      = unsubscribe_payload
        self._route              = route
        self._keepalive_payload  = keepalive_payload
        self._keepalive_interval = keepalive_interval
        self._queue_size         = queue_size
        self._answer             = answer
        self._request_key        = request_key or self._payload_id

        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._subscribed_topics: Set[str] = set()
        self._answers: Dict[str, asyncio.Future] = {}
        self._requests: Dict[str, List[str]] = {}
        self._lock      = asyncio.Lock()
        self._connected = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._ws        = None
        self._last_seen = 0.0
        self._closed    = False
        self._log       = logging.getLogger(name)


    async def subscribe(self, topic: str) -> asyncio.Queue:
        q            = asyncio.Queue(maxsize=self._queue_size)
        is_new_topic = False

        async with self._lock:
            if topic not in self._queues:
                self._queues[topic] = []
                is_new_topic       = True
                if self._answer is not None:
                    self._answers[topic] = asyncio.get_running_loop().create_future()
            self._queues[topic].append(q)
            answered = self._answers.get(topic)
            if not self._closed and (self._task is None or self._task.done()):
                self._task = asyncio.create_task(self._run())

        try:
            if is_new_topic:
                try:
                    await asyncio.wait_for(self._connected.wait(), timeout=self.ANSWER_S)
                except asyncio.TimeoutError:
                    raise UpstreamUnavailableError(f"{self.name} could not reach the venue in {self.ANSWER_S} s to subscribe {topic}")

                send_now = False
                async with self._lock:
                    if topic not in self._subscribed_topics:
                        self._subscribed_topics.add(topic)
                        send_now = True
                if send_now:
                    await self._send_payloads(self._sub_payload([topic]), [topic])

            if answered is not None:
                try:
                    refusal = await asyncio.wait_for(asyncio.shield(answered), timeout=self.ANSWER_S)
                except asyncio.TimeoutError:
                    raise UpstreamUnavailableError(f"{self.name} gave no answer in {self.ANSWER_S} s to the subscription of {topic}")
                if refusal is not None:
                    raise SubscriptionRefused(f"{self.name} refused {topic}: {refusal}")
        except BaseException:
            await self.unsubscribe(topic, q)
            raise

        return q


    async def unsubscribe(self, topic: str, q: Optional[asyncio.Queue]) -> None:
        drop_topic = False

        async with self._lock:
            qs = self._queues.get(topic) or []
            qs = [x for x in qs if x is not q]
            if qs:
                self._queues[topic] = qs
            else:
                self._queues.pop(topic, None)
                drop_topic = True
                self._subscribed_topics.discard(topic)
                self._answers.pop(topic, None)
                self._requests = {key: [t for t in topics if t != topic] for key, topics in self._requests.items() if topics != [topic]}

        if drop_topic and self._connected.is_set():
            await self._send_payloads(self._unsub_payload([topic]))


    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            task         = self._task
            self._task   = None

        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


    async def _send_payloads(self, payloads: Iterable[Any], topics: Iterable[str] = ()) -> None:
        ws = self._ws
        if ws is None:
            return

        payloads = list(payloads)
        topics   = list(topics)
        one_each = len(payloads) == len(topics)
        for i, payload in enumerate(payloads):
            key = self._request_key(payload) if topics else None
            if key is not None:
                self._requests[key] = [topics[i]] if one_each else topics
            try:
                if isinstance(payload, (str, bytes)):
                    await ws.send(payload)
                else:
                    await ws.send(orjson.dumps(payload).decode())
            except Exception as e:
                self._log.warning(f"send failed: {e}")
                return


    @staticmethod
    def _payload_id(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            for key in ("id", "req_id"):
                if payload.get(key) is not None:
                    return str(payload[key])
        return None


    def _settle(self, key: str, refusal: Optional[str]) -> None:
        topics = self._requests.pop(key, None)
        if topics is None:
            topics         = [key]
            self._requests = {k: [t for t in ts if t != key] for k, ts in self._requests.items() if ts != [key]}
        for topic in topics:
            answered = self._answers.get(topic)
            if answered is None:
                continue
            if not answered.done():
                answered.set_result(refusal)
            elif refusal is not None:
                self._log.warning(f"{topic} refused on resubscription: {refusal}")


    async def _keepalive_loop(self, ws: Any) -> None:
        try:
            while True:
                await asyncio.sleep(self._keepalive_interval)
                if time.monotonic() - self._last_seen > 2 * self._keepalive_interval:
                    self._log.warning(f"no frame for {2 * self._keepalive_interval:.0f} s; reconnecting")
                    await ws.close()
                    return
                if self._keepalive_payload is None:
                    continue
                if isinstance(self._keepalive_payload, (str, bytes)):
                    await ws.send(self._keepalive_payload)
                else:
                    await ws.send(orjson.dumps(self._keepalive_payload).decode())
        except (asyncio.CancelledError, Exception):
            return


    @staticmethod
    def _parse(raw: Any) -> Any:
        if isinstance(raw, (bytes, bytearray)):
            try:
                return orjson.loads(raw)
            except orjson.JSONDecodeError:
                return None
        if isinstance(raw, str):
            try:
                return orjson.loads(raw)
            except orjson.JSONDecodeError:
                return None
        return raw


    async def _run(self) -> None:
        reconnect_delay = 1

        while not self._closed:
            ka_task: Optional[asyncio.Task] = None
            ws = None

            try:
                self._log.info("connecting upstream WS")
                ws              = await self._connect()
                self._ws        = ws
                self._last_seen = time.monotonic()

                async with self._lock:
                    topics                  = list(self._queues.keys())
                    self._subscribed_topics = set(topics)
                if topics:
                    await self._send_payloads(self._sub_payload(topics), topics)

                self._connected.set()

                if self._keepalive_payload is not None and self._keepalive_interval > 0:
                    ka_task = asyncio.create_task(self._keepalive_loop(ws))

                stable = False
                async for raw in ws:
                    self._last_seen = time.monotonic()
                    if not stable:
                        reconnect_delay = 1
                        stable          = True
                    msg = self._parse(raw)
                    if msg is None:
                        continue
                    answer = self._answer(msg) if self._answer is not None else None
                    if answer is not None:
                        self._settle(*answer)
                        continue
                    topic = self._route(msg)
                    if topic is None:
                        continue
                    queues = self._queues.get(topic) or []
                    for q in queues:
                        try:
                            q.put_nowait(msg)
                        except asyncio.QueueFull:
                            try:
                                q.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            try:
                                q.put_nowait(msg)
                            except asyncio.QueueFull:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log.warning(f"upstream WS disconnected ({e}). Reconnecting in {reconnect_delay}s...")
            finally:
                self._connected.clear()
                self._ws = None
                if ka_task is not None:
                    ka_task.cancel()
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass

            if not self._closed:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)


class BaseExchange(ABC):
    INFO_REFRESH_S = 24 * 60 * 60
    INFO_RETRY_S   = 60 * 60
    INFO_MISS_S    = 60
    INFO_RECORD_S  = 5 * 60


    def __init__(self):
        self._info_cache: Dict[MarketType, Dict[str, SymbolInfo]] = {}
        self._info_cache_at: Dict[MarketType, float] = {}
        self._info_missed_at: Dict[MarketType, float] = {}
        self._info_cache_lock = asyncio.Lock()
        self._margin_cache: Dict[Any, Tuple[float, Any, int]] = {}
        self._margin_locks: Dict[Any, asyncio.Lock] = {}
        self._warm_task: Optional[asyncio.Task] = None


    @abstractmethod
    async def shutdown(self):
        pass


    def normalize_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()


    def get_api_symbol(self, symbol: str, market_type: MarketType) -> str:
        return self.normalize_symbol(symbol)


    def get_model_symbol(self, api_symbol: str, market_type: MarketType) -> str:
        return self.normalize_symbol(api_symbol)


    def normalize_timestamp(self, ts: Union[int, float, str]) -> int:
        if isinstance(ts, str):
            try:
                ts = float(ts)
            except ValueError:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    raise ValueError(f"Could not parse timestamp string: {ts}")
        if isinstance(ts, (int, float)):
            if ts < 100_000_000_000:
                return int(ts * 1000)
            return int(ts)
        raise ValueError(f"Unsupported timestamp format: {type(ts)}")


    async def _paginate_backwards(self, fetch_func_by_end: Callable, total_limit: int, limit_per_req: int, extra_rows: int = 0) -> List[Any]:
        chunks = []
        seen = set()
        collected = 0
        current_end = None
        max_requests = 100
        req_count = 0
        wanted = total_limit + extra_rows

        if wanted > max_requests * limit_per_req:
            raise ValueError(f"limit {total_limit} is more than {self.name} serves in one request; the most is {max_requests * limit_per_req - extra_rows}")

        while collected < wanted and req_count < max_requests:
            batch = await fetch_func_by_end(current_end, limit_per_req)
            if not batch:
                break

            batch.sort(key=lambda x: x.timestamp)
            new_items = []
            for x in batch:
                key = x.model_dump_json()
                if key not in seen:
                    seen.add(key)
                    new_items.append(x)
            if not new_items:
                break

            chunks.append(new_items)
            collected += len(new_items)
            req_count += 1
            next_end = batch[0].timestamp
            if next_end <= 0 or (current_end is not None and next_end >= current_end):
                break
            current_end = next_end

        if req_count >= max_requests and collected < wanted:
            raise ValueError(f"limit {total_limit} took more than {max_requests} pages on {self.name}; the most one request reached is {max(collected - extra_rows, 0)}")

        chunks.reverse()
        out = [item for chunk in chunks for item in chunk]
        out.sort(key=lambda x: x.timestamp)
        return out[-wanted:]


    @property
    @abstractmethod
    def name(self) -> str:
        pass


    @property
    @abstractmethod
    def supported_market_types(self) -> List[MarketType]:
        pass


    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        pass


    async def get_status(self) -> Dict[str, Any]:
        return {"status": "online", "exchange": self.name}


    async def preload(self) -> None:
        if type(self)._warm is BaseExchange._warm:
            return

        self._warm_task = asyncio.create_task(self._run_warm())


    async def cancel_warm(self) -> None:
        task            = self._warm_task
        self._warm_task = None
        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


    async def _run_warm(self) -> None:
        started = time.monotonic()
        logger.info(f"[{self.name}] preload: starting")

        try:
            await self._warm()
            elapsed = time.monotonic() - started
            logger.info(f"[{self.name}] preload: done in {elapsed:.1f}s")

        except Exception:
            elapsed = time.monotonic() - started
            logger.exception(f"[{self.name}] preload: aborted after {elapsed:.1f}s")


    async def _step(self, name: str, awaitable: Awaitable[Any]) -> None:
        started = time.monotonic()
        logger.info(f"[{self.name}] preload: warming {name}...")

        try:
            await awaitable
            elapsed = time.monotonic() - started
            logger.info(f"[{self.name}] preload: {name} ready in {elapsed:.1f}s")

        except Exception:
            elapsed = time.monotonic() - started
            logger.exception(f"[{self.name}] preload: {name} failed after {elapsed:.1f}s")
            raise


    async def _warm(self) -> None:
        return None


    async def _fetch_exchange_info(self, market_type: MarketType) -> List[SymbolInfo]:
        raise NotImplementedError(f"Exchange info fetch not implemented on {self.name}")


    async def _ensure_info_cache(self, market_type: MarketType, max_age_s: Optional[float] = None) -> Dict[str, SymbolInfo]:
        async with self._info_cache_lock:
            now     = time.monotonic()
            cached  = self._info_cache.get(market_type)
            elapsed = now - self._info_cache_at.get(market_type, 0.0)

            if cached is not None and elapsed < (self.INFO_REFRESH_S if max_age_s is None else max_age_s):
                return cached

            try:
                infos = await self._fetch_exchange_info(market_type)
            except Exception:
                if cached is None:
                    raise
                logger.warning(f"[{self.name}] exchange info refresh failed for {market_type.value}; serving cached metadata")
                self._info_cache_at[market_type] = now - self.INFO_REFRESH_S + self.INFO_RETRY_S
                return cached

            self._info_cache[market_type] = {info.symbol: info for info in infos}
            self._info_cache_at[market_type] = now

            return self._info_cache[market_type]


    async def _info_for(self, market_type: MarketType, model_symbol: str) -> Optional[SymbolInfo]:
        cache = await self._ensure_info_cache(market_type)
        return cache.get(model_symbol)


    async def _listed_info(self, market_type: MarketType, status: str = "trading") -> Dict[str, SymbolInfo]:
        if status != "all" and status not in STATUSES:
            raise ValueError(f"status: '{status}' is not a market state; give all, {', '.join(STATUSES[:-1])} or {STATUSES[-1]}")

        cache = await self._ensure_info_cache(market_type)
        if status == "all":
            return dict(cache)
        return {symbol: info for symbol, info in cache.items() if info.status == status}


    async def symbol_record(self, market_type: MarketType, symbol: str) -> SymbolInfo:
        name   = await self.listed_symbol(market_type, symbol)
        cache  = await self._ensure_info_cache(market_type, max_age_s=self.INFO_RECORD_S)
        record = cache.get(name)

        if record is None:
            raise ValueError(f"symbol '{symbol}' is not listed on {self.name} {market_type.value}; see /{self.name}/{market_type.value}/markets")
        return record


    def _alias(self, market_type: MarketType, symbol: str) -> Optional[str]:
        return None


    def _listed_name(self, cache: Dict[str, SymbolInfo], market_type: MarketType, symbol: str) -> Optional[str]:
        name = self.get_model_symbol(self.get_api_symbol(symbol, market_type), market_type)
        if name in cache:
            return name
        alias = self._alias(market_type, symbol)
        return alias if alias in cache else None


    async def listed_symbol(self, market_type: MarketType, symbol: str) -> str:
        cache = await self._ensure_info_cache(market_type)
        name  = self._listed_name(cache, market_type, symbol)

        if name is None and time.monotonic() - self._info_missed_at.get(market_type, float("-inf")) >= self.INFO_MISS_S:
            self._info_missed_at[market_type] = time.monotonic()
            cache = await self._ensure_info_cache(market_type, max_age_s=0)
            name  = self._listed_name(cache, market_type, symbol)

        if name is None:
            raise ValueError(f"symbol '{symbol}' is not listed on {self.name} {market_type.value}; see /{self.name}/{market_type.value}/markets")
        return name


    async def _margin_table(self, key: Any, fetch: Callable[[], Awaitable[Any]]) -> Tuple[Any, int]:
        lock = self._margin_locks.setdefault(key, asyncio.Lock())

        async with lock:
            now    = time.monotonic()
            cached = self._margin_cache.get(key)

            if cached is not None and now - cached[0] < self.INFO_REFRESH_S:
                return cached[1], cached[2]

            try:
                rows = await fetch()
            except Exception:
                if cached is None:
                    raise
                logger.warning(f"[{self.name}] margin tiers refresh failed for {key}; serving the cached table")
                self._margin_cache[key] = (now - self.INFO_REFRESH_S + self.INFO_RETRY_S, cached[1], cached[2])
                return cached[1], cached[2]

            read_at = int(time.time() * 1000)
            self._margin_cache[key] = (now, rows, read_at)

            return rows, read_at


    @abstractmethod
    async def get_exchange_info(self, market_type: MarketType, status: str = "trading") -> List[SymbolInfo]:
        pass


    @abstractmethod
    async def get_ticker(self, market_type: MarketType, symbol: str) -> Ticker:
        pass


    @abstractmethod
    async def get_book_ticker(self, market_type: MarketType, symbol: str) -> BookTicker:
        pass


    async def get_mark_price(self, market_type: MarketType, symbol: str) -> MarkPrice:
        raise NotImplementedError(f"Mark Price not supported on {self.name} {market_type}")


    @abstractmethod
    async def get_orderbook(self, market_type: MarketType, symbol: str, depth: int = 20) -> OrderBook:
        pass


    @abstractmethod
    async def get_trades(self, market_type: MarketType, symbol: str, limit: int = 100) -> List[Trade]:
        pass


    @abstractmethod
    async def get_agg_trades(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 500) -> List[AggTrade]:
        pass


    @abstractmethod
    async def get_candles(self, market_type: MarketType, symbol: str, interval: str, start_time: Optional[int] = None, limit: int = 100) -> List[Candle]:
        pass


    @abstractmethod
    async def stream_ticker(self, market_type: MarketType, symbol: str) -> AsyncGenerator[Ticker, None]:
        pass


    @abstractmethod
    async def stream_book_ticker(self, market_type: MarketType, symbol: str) -> AsyncGenerator[BookTicker, None]:
        pass


    async def stream_mark_price(self, market_type: MarketType, symbol: str) -> AsyncGenerator[MarkPrice, None]:
        if False: yield
        raise NotImplementedError(f"Mark Price stream not supported on {self.name} {market_type}")


    async def stream_agg_trades(self, market_type: MarketType, symbol: str) -> AsyncGenerator[AggTrade, None]:
        if False: yield
        raise NotImplementedError(f"AggTrade stream not supported on {self.name} {market_type}")


    @abstractmethod
    async def stream_trades(self, market_type: MarketType, symbol: str) -> AsyncGenerator[Trade, None]:
        pass


    @abstractmethod
    async def stream_orderbook(self, market_type: MarketType, symbol: str, depth: int = 20, update_speed: str = "100ms") -> AsyncGenerator[OrderBook, None]:
        pass


    async def stream_liquidations(self, market_type: MarketType, symbol: str) -> AsyncGenerator[Liquidation, None]:
        if False: yield
        raise NotImplementedError(f"Liquidation stream not supported on {self.name} {market_type}")


    async def get_open_interest(self, market_type: MarketType, symbol: str, period: str = "1h", start_time: Optional[int] = None, limit: int = 30) -> List[OpenInterest]:
        raise NotImplementedError(f"Open Interest not supported on {self.name} {market_type}")


    async def get_funding_rate(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 100) -> List[FundingRate]:
        raise NotImplementedError(f"Funding Rate not supported on {self.name} {market_type}")


    async def get_liquidations(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 100) -> List[Liquidation]:
        raise NotImplementedError(f"Liquidations not supported on {self.name} {market_type}")


    async def get_long_short_ratio(self, market_type: MarketType, symbol: str, period: str = "5m", start_time: Optional[int] = None, limit: int = 30) -> List[LongShortRatio]:
        raise NotImplementedError(f"L/S Ratio not supported on {self.name} {market_type}")


    async def get_margin_tiers(self, market_type: MarketType, symbol: str) -> MarginTiers:
        raise NotImplementedError(f"Margin tiers not supported on {self.name} {market_type.value}")
