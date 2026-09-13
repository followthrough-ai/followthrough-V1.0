"""Real integrations share the mock interface: find_*() + execute(action, **p).
They are ONLY used by `run.py live` and `run.py check`. Never point evaluation at
production accounts — use a sandbox workspace/base/account."""
import json, time, urllib.error, urllib.request
from ..reliability.fault_injection import TransientError

class ApiError(Exception):
    """A real API call failed. outcome_unknown=True means a write may still have
    applied (e.g. a timeout on POST), so it must not be retried automatically."""
    def __init__(self, message: str, outcome_unknown: bool = False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown

# Writes that are safe to repeat: re-sending them cannot create a duplicate.
_REPEATABLE = ("GET", "PATCH", "PUT", "DELETE")

def _once(method: str, url: str, headers: dict, body: dict | None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **headers})
    repeatable = method in _REPEATABLE
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 429:
            raise TransientError("rate_limit_429") from e      # rejected, nothing applied
        if e.code >= 500 and repeatable:
            raise TransientError("server_error") from e
        raise ApiError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {detail}",
                       outcome_unknown=e.code >= 500) from e
    except (TimeoutError, urllib.error.URLError) as e:
        timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
        if timed_out and repeatable:
            raise TransientError("timeout") from e
        raise ApiError(f"{method} {url.split('?')[0]} -> {e}", outcome_unknown=timed_out) from e

def http(method: str, url: str, headers: dict, body: dict | None = None, attempts: int = 3):
    """One API call. Reads retry transient failures here; writes surface
    TransientError so the executor's idempotent retry loop handles them."""
    if method != "GET":
        return _once(method, url, headers, body)
    for i in range(attempts):
        try:
            return _once(method, url, headers, body)
        except TransientError as e:
            if i == attempts - 1:
                raise ApiError(f"GET {url.split('?')[0]} still failing after "
                               f"{attempts} tries ({e.kind})") from e
            time.sleep(1.5 * (i + 1))
