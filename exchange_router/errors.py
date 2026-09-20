from typing import Optional


class RouterError(Exception):

    def __init__(self, detail: str, status: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        self.status = status


    def __str__(self) -> str:
        if self.status is not None:
            return f"[{self.status}] {self.detail}"
        return self.detail


class BadRequest(RouterError):
    pass


class NotFound(RouterError):
    pass


class RateLimited(RouterError):
    pass


class UpstreamUnavailable(RouterError):

    def __init__(self, detail: str, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(detail, status)
        self.retry_after = retry_after


class NotSupported(RouterError):
    pass


class RouterUnreachable(RouterError):
    pass


class SchemaMismatch(RouterError):

    def __init__(self, detail: str, sdk_schema: Optional[int] = None, service_schema: Optional[int] = None):
        super().__init__(detail)
        self.sdk_schema     = sdk_schema
        self.service_schema = service_schema


def error_for_status(status: int, detail: str, retry_after: Optional[float] = None) -> RouterError:
    if status == 400:
        return BadRequest(detail, status)

    if status == 404:
        return NotFound(detail, status)

    if status == 429:
        return RateLimited(detail, status)

    if status == 501:
        return NotSupported(detail, status)

    if status == 503:
        return UpstreamUnavailable(detail, status, retry_after)

    return RouterError(detail, status)
