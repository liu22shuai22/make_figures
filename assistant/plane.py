"""Public entry for the assistant execution plane."""
from __future__ import annotations

from typing import Any

from .harness import execute_turn
from .memory import normalize_history
from .types import Locale, Surface, TurnContext, TurnResult


def run_turn(
    message: str,
    *,
    surface: Surface = "welcome",
    locale: Locale = "zh",
    diagram_kind: str = "er",
    spec: dict | None = None,
    authenticated: bool = False,
    history: list[Any] | None = None,
) -> TurnResult:
    ctx = TurnContext(
        message=message or "",
        surface=surface if surface in ("welcome", "workbench") else "welcome",
        locale=locale if locale in ("zh", "en") else "zh",
        diagram_kind=diagram_kind or "er",
        spec=spec,
        authenticated=bool(authenticated),
        history=normalize_history(history),
    )
    return execute_turn(ctx)
