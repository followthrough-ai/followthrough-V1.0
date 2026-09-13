"""Fault injection: wraps any integration and injects failures per a fault plan.

Fault plan (per fixture, optional file faults.json):
  [{"match": {"app": "gmail", "action": "send_email"},
    "faults": ["timeout", "rate_limit_429", "applied_but_lost"]}]

Semantics:
  timeout            -> raise TransientError BEFORE the side effect is applied
  rate_limit_429     -> raise TransientError BEFORE the side effect is applied
  applied_but_lost   -> APPLY the side effect, then raise TransientError
                        (the classic "write succeeded, response lost" case;
                        only idempotency keys can save you here)

Each listed fault fires once, in order, on successive attempts.
"""

class TransientError(Exception):
    def __init__(self, kind): super().__init__(kind); self.kind = kind

class FaultInjector:
    def __init__(self, plan: list[dict] | None):
        self.plan = plan or []
        self._fired: dict[int, int] = {}

    def _match(self, entry, app, action):
        m = entry.get("match", {})
        return (m.get("app") in (None, app)) and (m.get("action") in (None, action))

    def next_fault(self, app: str, action: str) -> str | None:
        for i, entry in enumerate(self.plan):
            if self._match(entry, app, action):
                fired = self._fired.get(i, 0)
                faults = entry.get("faults", [])
                if fired < len(faults):
                    self._fired[i] = fired + 1
                    return faults[fired]
        return None

class FaultyIntegration:
    """Decorator around a real/mock integration's execute()."""
    def __init__(self, inner, injector: FaultInjector, name: str):
        self.inner = inner
        self.injector = injector
        self.name = name

    def execute(self, action: str, **kwargs):
        fault = self.injector.next_fault(self.name, action)
        if fault in ("timeout", "rate_limit_429"):
            raise TransientError(fault)
        if fault == "applied_but_lost":
            self.inner.execute(action, **kwargs)   # side effect IS applied
            raise TransientError(fault)            # ...but caller never learns
        return self.inner.execute(action, **kwargs)

    def __getattr__(self, item):
        return getattr(self.inner, item)
