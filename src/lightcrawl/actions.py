"""Declarative action model for browser interactions (PR 5).

Each action describes one operation the browser performs after `page.goto`
and `wait_for` but before `page.content()`. Intermediate `ScreenshotAction`
entries produce PNGs that land under `screenshots[]` in the response, reusing
PR 2's unified array.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_MAX_INTERMEDIATE_SCREENSHOTS = 20
_MAX_WAIT_MS = 60_000  # one minute; beyond this exceeds typical timeouts
_MIN_TIMEOUT_MS = 100
_MAX_TIMEOUT_MS = 60_000
_VALID_DIRECTIONS = frozenset({"down", "up"})
# Keys that Playwright's page.keyboard.press() accepts. Case-sensitive.
_VALID_PRESS_KEYS = frozenset({
    "Enter", "Tab", "Escape", "Backspace", "Delete", "Space",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
})


@dataclass(frozen=True)
class ClickAction:
    selector: str
    timeout_ms: int = 5000


@dataclass(frozen=True)
class WriteAction:
    selector: str
    text: str
    timeout_ms: int = 5000


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
    WriteAction: frozenset({"selector", "text", "timeout_ms"}),
    PressAction: frozenset({"key"}),
    WaitAction: frozenset({"milliseconds"}),
    ScrollAction: frozenset({"pixels", "direction"}),
    ScreenshotAction: frozenset({"label"}),
}


def _check_int(label: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an int, got {type(value).__name__}")
    return value


def _validate_value(action: Action) -> None:
    """Post-construction value checks. Raises ValueError or TypeError on bad data.
    TypeError on wrong field types (e.g. `pixels="100"`) is caught by
    `parse_actions` and re-wrapped with the action index."""
    if isinstance(action, ScrollAction):
        if not isinstance(action.direction, str):
            raise TypeError(f"direction must be a string, got {type(action.direction).__name__}")
        if action.direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"scroll direction must be 'down' or 'up', got {action.direction!r}"
            )
        px = _check_int("pixels", action.pixels)
        if px <= 0:
            raise ValueError(f"scroll pixels must be positive, got {px}")
    elif isinstance(action, WaitAction):
        ms = _check_int("milliseconds", action.milliseconds)
        if ms < 0:
            raise ValueError(f"wait milliseconds must be >= 0, got {ms}")
        if ms > _MAX_WAIT_MS:
            raise ValueError(
                f"wait milliseconds must be <= {_MAX_WAIT_MS}, got {ms}"
            )
    elif isinstance(action, ClickAction):
        t = _check_int("timeout_ms", action.timeout_ms)
        if t < _MIN_TIMEOUT_MS or t > _MAX_TIMEOUT_MS:
            raise ValueError(
                f"timeout_ms must be between {_MIN_TIMEOUT_MS} and "
                f"{_MAX_TIMEOUT_MS}, got {t}"
            )
    elif isinstance(action, WriteAction):
        t = _check_int("timeout_ms", action.timeout_ms)
        if t < _MIN_TIMEOUT_MS or t > _MAX_TIMEOUT_MS:
            raise ValueError(
                f"timeout_ms must be between {_MIN_TIMEOUT_MS} and "
                f"{_MAX_TIMEOUT_MS}, got {t}"
            )
    elif isinstance(action, PressAction):
        if not isinstance(action.key, str):
            raise TypeError(f"key must be a string, got {type(action.key).__name__}")
        if action.key not in _VALID_PRESS_KEYS:
            raise ValueError(
                f"unknown press key {action.key!r}; Playwright key names are "
                f"case-sensitive. Allowed: {', '.join(sorted(_VALID_PRESS_KEYS))}"
            )


def from_dict(d: dict) -> Action:
    """Parse a single action dict. Raises ValueError on unknown type, unknown
    fields, or invalid values."""
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
    action = cls(**kwargs)  # type: ignore[call-arg]
    _validate_value(action)
    return action


def parse_actions(raw: list[dict] | None) -> list[Action]:
    """Parse a list of action dicts. Returns empty list for None/empty input.
    Raises ValueError on any invalid entry or when ScreenshotAction count
    exceeds the hard cap."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"actions must be a list, got {type(raw).__name__}")
    out: list[Action] = []
    screenshot_count = 0
    for i, item in enumerate(raw):
        try:
            action = from_dict(item)
        except (ValueError, TypeError) as e:
            raise ValueError(f"actions[{i}]: {e}") from e
        if isinstance(action, ScreenshotAction):
            screenshot_count += 1
            if screenshot_count > _MAX_INTERMEDIATE_SCREENSHOTS:
                raise ValueError(
                    f"max {_MAX_INTERMEDIATE_SCREENSHOTS} ScreenshotAction "
                    f"entries allowed; got at least {screenshot_count}"
                )
        out.append(action)
    return out
