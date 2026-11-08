import asyncio
from typing import Any, Dict, Optional, Tuple

from exchange_router.exchanges.base import UNREADABLE, RequestError, SubscriptionRefused, UnknownSymbolError, UpstreamUnavailableError


SEND_S = 5.0

TITLES = {
    400: "Invalid Request",
    404: "Not Found",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Upstream Response",
    503: "Upstream Unavailable",
}


def error_frame(status: int, detail: str, error: Optional[str] = None) -> Dict[str, str]:
    return {"error": error or TITLES[status], "detail": detail}


def status_of(exc: BaseException) -> Tuple[int, Optional[str]]:
    if isinstance(exc, UnknownSymbolError):
        return 400, "Unknown Symbol"
    if isinstance(exc, (RequestError, SubscriptionRefused)):
        return 400, None
    if isinstance(exc, NotImplementedError):
        return 501, None
    if isinstance(exc, UpstreamUnavailableError):
        return 503, None
    if isinstance(exc, UNREADABLE):
        return 502, None
    return 500, None


def close_code(status: int) -> int:
    return 1011 if status in (500, 502, 503) else 1003


def close_reason(text: str) -> str:
    return text.encode("utf-8")[:123].decode("utf-8", "ignore")


async def refuse(client: Any, status: int, detail: str, error: Optional[str] = None) -> None:
    try:
        await asyncio.wait_for(client.send_json(error_frame(status, detail, error)), timeout=SEND_S)
    except Exception:
        pass
    try:
        await asyncio.wait_for(client.close(code=close_code(status), reason=close_reason(detail)), timeout=SEND_S)
    except Exception:
        pass
