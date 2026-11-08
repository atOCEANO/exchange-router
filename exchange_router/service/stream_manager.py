import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket
from exchange_router.exchanges.base import control_frame, stream_events
from exchange_router.service.answers import close_reason, refuse, status_of


class StreamManager:

    def __init__(self):
        self.active_streams: Dict[str, Dict[uuid.UUID, WebSocket]] = {}
        self.upstream_tasks: Dict[str, asyncio.Task] = {}
        self._closing: Set[asyncio.Task] = set()
        self._sending: Set[asyncio.Task] = set()
        self._live: Dict[str, Dict[str, Any]] = {}
        self._send_locks: Dict[str, asyncio.Lock] = {}
        self._pending: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()


    async def subscribe(self, key: str, websocket: WebSocket, adapter, market_type, channel, symbol) -> uuid.UUID:
        client_id = uuid.uuid4()
        async with self._lock:
            if key not in self.active_streams:
                self._live.pop(key, None)
                self._pending.pop(key, None)
                self.active_streams[key] = {client_id: websocket}
                self.upstream_tasks[key] = asyncio.create_task(
                    self._upstream_handler(key, adapter, market_type, channel, symbol)
                )
                return client_id

        async with self._send_locks.setdefault(key, asyncio.Lock()):
            dead_items = await self._deliver_all(self.active_streams.get(key) or {}, self._pending.pop(key, []))
            if key in self._live:
                frame       = control_frame("subscribed", channel, symbol, int(time.time() * 1000))
                dead_items += await self._deliver_all({client_id: websocket}, [json.dumps(frame)])
            async with self._lock:
                bucket = self.active_streams.get(key)
                if bucket is not None:
                    bucket[client_id] = websocket

        if bucket is None:
            await refuse(websocket, 503, f"the venue ended the {channel} stream of {symbol}; subscribe again")
            return client_id
        await self._remove_dead(key, dead_items)
        return client_id


    async def unsubscribe(self, key: str, client_id: uuid.UUID) -> None:
        task: Optional[asyncio.Task] = None
        async with self._lock:
            if key in self.active_streams:
                self.active_streams[key].pop(client_id, None)
                if not self.active_streams[key]:
                    task = self.upstream_tasks.pop(key, None)
                    self.active_streams.pop(key, None)
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass


    async def shutdown(self) -> None:
        tasks = list(self.upstream_tasks.values())
        self.upstream_tasks.clear()
        self.active_streams.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        pending = list(self._closing) + list(self._sending)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


    async def _close_client(self, client: WebSocket, reason: str, code: int = 1011) -> None:
        try:
            await asyncio.wait_for(client.close(code=code, reason=close_reason(reason)), timeout=5.0)
        except Exception:
            pass


    def _spawn_close(self, client: WebSocket, reason: str) -> None:
        task = asyncio.create_task(self._close_client(client, reason))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)


    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._sending.add(task)
        task.add_done_callback(self._sending.discard)


    async def _deliver(self, client: WebSocket, texts: List[str]) -> None:
        for text in texts:
            await asyncio.wait_for(client.send_text(text), timeout=5.0)


    async def _broadcast(self, key: str, text: Optional[str]) -> bool:
        async with self._send_locks.setdefault(key, asyncio.Lock()):
            bucket = self.active_streams.get(key)
            if not bucket:
                return False

            texts = self._pending.pop(key, []) + ([text] if text is not None else [])
            if not texts:
                return True

            dead_items = await self._deliver_all(bucket, texts)
        return await self._remove_dead(key, dead_items)


    async def _deliver_all(self, bucket: Dict[uuid.UUID, WebSocket], texts: List[str]) -> List:
        client_items = list(bucket.items())
        results      = await asyncio.gather(
            *[self._deliver(client, texts) for _, client in client_items],
            return_exceptions=True,
        )
        return [(cid, client) for (cid, client), res in zip(client_items, results) if isinstance(res, BaseException)]


    async def _remove_dead(self, key: str, dead_items: List) -> bool:
        if not dead_items:
            return True

        emptied, task = False, None
        for _, client in dead_items:
            self._spawn_close(client, "Send timeout")
        async with self._lock:
            current = self.active_streams.get(key)
            if current is not None:
                for cid, _ in dead_items:
                    current.pop(cid, None)
                if not current:
                    self.active_streams.pop(key, None)
                    task    = self.upstream_tasks.pop(key, None)
                    emptied = True
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return not emptied


    async def _upstream_handler(self, key, adapter, market_type, channel, symbol) -> None:
        status, error, detail = 503, None, f"the venue ended the {channel} stream of {symbol}; subscribe again"
        handler               = asyncio.current_task()
        refusal               = {}

        def event(kind: str, ts: int, reason: Optional[str] = None) -> None:
            if kind == "refused":
                refusal["detail"] = reason
                handler.cancel()
                return
            frame = control_frame(kind, channel, symbol, ts)
            if kind == "subscribed":
                self._live[key] = frame
            else:
                self._live.pop(key, None)
            self._pending.setdefault(key, []).append(json.dumps(frame))
            self._spawn(self._broadcast(key, None))

        stream_events.set(event)
        try:
            if   channel == "ticker":       stream = adapter.stream_ticker(market_type, symbol)
            elif channel == "book_ticker":  stream = adapter.stream_book_ticker(market_type, symbol)
            elif channel == "mark_price":   stream = adapter.stream_mark_price(market_type, symbol)
            elif channel == "agg_trades":   stream = adapter.stream_agg_trades(market_type, symbol)
            elif channel == "trades":       stream = adapter.stream_trades(market_type, symbol)
            elif channel == "orderbook":    stream = adapter.stream_orderbook(market_type, symbol)
            elif channel == "liquidations": stream = adapter.stream_liquidations(market_type, symbol)
            else: return

            async for item in stream:
                if not await self._broadcast(key, item.model_dump_json()):
                    break
        except asyncio.CancelledError:
            if refusal:
                status, detail = 400, refusal["detail"]
        except Exception as e:
            logging.error(f"Upstream stream error for {key}: {e}")
            status, error = status_of(e)
            detail        = str(e) or detail
        finally:
            if self.upstream_tasks.get(key) in (None, asyncio.current_task()):
                self._live.pop(key, None)
            close_tasks = []
            async with self._lock:
                if self.upstream_tasks.get(key) is asyncio.current_task():
                    self.upstream_tasks.pop(key, None)
                    bucket = self.active_streams.pop(key, None)
                    if bucket:
                        for client in bucket.values():
                            close_tasks.append(asyncio.create_task(refuse(client, status, detail, error)))
                if key not in self.upstream_tasks:
                    self._pending.pop(key, None)
            for t in close_tasks:
                try:
                    await t
                except Exception:
                    pass
