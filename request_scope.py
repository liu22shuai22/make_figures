"""Credentials and identity scoped to a single HTTP request."""
from contextvars import ContextVar
from dataclasses import dataclass, field

@dataclass
class RequestScope:
    username: str | None
    store: dict = field(default_factory=lambda: {"active_id": None, "providers": []})
    endpoints: dict = field(default_factory=dict)
    model_depth: int = 0

current_scope: ContextVar[RequestScope | None] = ContextVar("erflow_request", default=None)
