"""Declarative action model for browser interactions (PR 5).

Each action describes one operation the browser performs after `page.goto`
and `wait_for` but before `page.content()`. Intermediate `ScreenshotAction`
entries produce PNGs that land under `screenshots[]` in the response, reusing
PR 2's unified array.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ClickAction:
    selector: str
    timeout_ms: int = 5000


@dataclass(frozen=True)
class WriteAction:
    selector: str
    text: str


@dataclass(frozen=True)
class PressAction:
    key: str  # "Enter" | "Tab" | "Escape" | "ArrowDown" | ...


@dataclass(frozen=True)
class WaitAction:
    milliseconds: int


@dataclass(frozen=True)
class ScrollAction:
    pixels: int = 800
    direction: Literal["down", "up"] = "down"


@dataclass(frozen=True)
class ScreenshotAction:
    label: str | None = None


Action = ClickAction | WriteAction | PressAction | WaitAction | ScrollAction | ScreenshotAction

_TYPE_MAP: dict[str, type[Action]] = {
    "click": ClickAction,
    "write": WriteAction,
    "press": PressAction,
    "wait": WaitAction,
    "scroll": ScrollAction,
    "screenshot": ScreenshotAction,
}

_FIELD_MAP: dict[type[Action], frozenset[str]] = {
    ClickAction: frozenset({"selector", "timeout_ms"}),
    WriteAction: frozenset({"selector", "text"}),
    PressAction: frozenset({"key"}),
    WaitAction: frozenset({"milliseconds"}),
    ScrollAction: frozenset({"pixels", "direction"}),
    ScreenshotAction: frozenset({"label"}),
}


def from_dict(d: dict) -> Action:
    """Parse a single action dict. Raises ValueError on unknown type or fields."""
    if not isinstance(d, dict):
        raise ValueError(f"action must be a dict, got {type(d).__name__}")
    raw_type = d.get("type")
    if not isinstance(raw_type, str):
        raise ValueError(f"action must have a string 'type' key, got {raw_type!r}")
    cls = _TYPE_MAP.get(raw_type.lower())
    if cls is None:
        raise ValueError(
            f"unknown action type {raw_type!r}; expected one of: "
            f"{', '.join(sorted(_TYPE_MAP))}"
        )
    allowed = _FIELD_MAP[cls]
    unknown = set(d.keys()) - {"type"} - allowed
    if unknown:
        raise ValueError(
            f"{raw_type} action has unknown fields: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    kwargs = {k: v for k, v in d.items() if k != "type"}
    return cls(**kwargs)  # type: ignore[call-arg]


def parse_actions(raw: list[dict] | None) -> list[Action]:
    """Parse a list of action dicts. Returns empty list for None/empty input.
    Raises ValueError on any invalid entry."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"actions must be a list, got {type(raw).__name__}")
    out: list[Action] = []
    for i, item in enumerate(raw):
        try:
            out.append(from_dict(item))
        except ValueError as e:
            raise ValueError(f"actions[{i}]: {e}") from e
    return out
