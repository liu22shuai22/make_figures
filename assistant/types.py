"""Shared types for one assistant turn."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Band = Literal["local_faq", "product_tool", "refuse", "open_review", "web_search"]
Surface = Literal["welcome", "workbench"]
Locale = Literal["zh", "en"]


@dataclass
class TurnContext:
    message: str
    surface: Surface = "welcome"
    locale: Locale = "zh"
    diagram_kind: str = "er"
    spec: dict | None = None
    authenticated: bool = False
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class RoutePlan:
    band: Band
    tool: str | None = None
    reason: str = ""


@dataclass
class TurnMessage:
    role: Literal["bot"]
    text: str


@dataclass
class TurnResult:
    band: Band
    messages: list[TurnMessage] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    cardinality: dict[str, Any] | None = None
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "messages": [{"role": item.role, "text": item.text} for item in self.messages],
            "actions": self.actions,
            "cardinality": self.cardinality,
            "trace": self.trace,
        }
