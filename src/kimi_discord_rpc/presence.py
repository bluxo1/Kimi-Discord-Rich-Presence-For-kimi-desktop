"""Turn a :class:`KimiState` into a Discord Rich Presence payload.

Discord gives you two free text lines (``details`` and ``state``) plus an
elapsed-time line it renders itself from ``start``. Fields are therefore
composed in priority order and truncated to fit rather than dropped wholesale,
with the overflow moved into the image hover text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import DisplayConfig
from .git_reader import BranchInfo, branch_label
from .kimi_detector import KimiState
from .models import display_name, format_context_window

# Discord's limits on presence strings.
MAX_FIELD = 128
MIN_FIELD = 2

SEPARATOR = " · "  # middle dot


@dataclass
class PresencePayload:
    details: str | None = None
    state: str | None = None
    start: int | None = None
    large_image: str | None = None
    large_text: str | None = None
    small_image: str | None = None
    small_text: str | None = None
    buttons: list[dict[str, str]] = field(default_factory=list)

    def to_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``pypresence.Presence.update``."""
        payload: dict[str, Any] = {}
        if self.details:
            payload["details"] = self.details
        if self.state:
            payload["state"] = self.state
        if self.start:
            payload["start"] = self.start
        if self.large_image:
            payload["large_image"] = self.large_image
        if self.large_text:
            payload["large_text"] = self.large_text
        if self.small_image:
            payload["small_image"] = self.small_image
        if self.small_text:
            payload["small_text"] = self.small_text
        if self.buttons:
            payload["buttons"] = self.buttons
        return payload

    def key(self) -> tuple:
        return (
            self.details,
            self.state,
            self.start,
            self.large_image,
            self.large_text,
            self.small_image,
            self.small_text,
        )


def _fit(text: str | None) -> str | None:
    """Clamp to Discord's field limits; too-short strings are rejected."""
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) < MIN_FIELD:
        return None
    if len(cleaned) > MAX_FIELD:
        cleaned = cleaned[: MAX_FIELD - 1].rstrip() + "…"
    return cleaned


def _join(parts: list[str | None]) -> str | None:
    present = [p for p in parts if p]
    return SEPARATOR.join(present) if present else None


def format_elapsed(seconds: float | None) -> str:
    """``HH:MM:SS`` for CLI output (Discord renders its own timer)."""
    if seconds is None or seconds < 0:
        return "--:--:--"
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def format_quota(state: KimiState) -> str | None:
    """Account quota consumed, e.g. ``4.6% quota used``.

    Kimi Desktop does not expose per-message token counts to the local
    machine, so this is the closest honest equivalent to a usage meter.
    """
    if state.quota_exhausted:
        return "quota exhausted"
    if state.quota_used_ratio is None:
        return None
    percent = max(0.0, min(1.0, state.quota_used_ratio)) * 100
    text = f"{percent:.0f}%" if percent >= 10 else f"{percent:.1f}%"
    return f"{text} quota used"


def format_quota_reset(state: KimiState) -> str | None:
    if not state.quota_reset_at:
        return None
    raw = state.quota_reset_at.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    local = parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc).astimezone()
    return f"resets {local.strftime('%b %d')}"


def build_payload(
    state: KimiState,
    display: DisplayConfig,
    branch: BranchInfo | None,
    large_image: str | None = None,
    small_image: str | None = None,
    buttons: list[dict[str, str]] | None = None,
    idle: bool = False,
) -> PresencePayload:
    """Compose the presence card for the current state."""
    payload = PresencePayload(
        large_image=large_image or None,
        small_image=small_image or None,
        buttons=list(buttons or []),
    )

    if not state.running:
        payload.details = _fit(display.idle_text)
        payload.large_text = _fit("Kimi Desktop is not running")
        return payload

    model = display_name(state.model_key) if display.show_model else None
    context = format_context_window(state.context_window) if display.show_context_window else None
    quota = format_quota(state) if display.show_quota else None
    branch_name = branch_label(branch) if display.show_git_branch else None

    # Line 1: what is being worked on.
    project = state.project_name if display.show_project else None
    if project:
        head = f"\U0001f4c1 {project}"
    elif state.surface == "agent":
        head = "\U0001f916 Kimi Agent"
    else:
        head = f"\U0001f4ac {display.chatting_text}"
    if branch_name:
        head = _join([head, f"\U0001f33f {branch_name}"]) or head
    payload.details = _fit(head)

    # Line 2: which model, and how much of the allowance is gone.
    model_text = f"\U0001f9e0 {model}" if model else None
    payload.state = _fit(_join([model_text, context, quota]))

    if display.show_file and state.filename:
        payload.state = _fit(_join([model_text, f"\U0001f4c4 {state.filename}", quota]))

    # Elapsed time: Discord renders this itself from the session start.
    if display.show_session_timer and state.session_started_at:
        payload.start = int(state.session_started_at)

    payload.large_text = _fit(_build_hover(state, display, model, branch_name))
    payload.small_text = _fit(display.idle_text if idle else _build_small_text(state))
    return payload


def _build_hover(
    state: KimiState,
    display: DisplayConfig,
    model: str | None,
    branch_name: str | None,
) -> str | None:
    parts: list[str | None] = [model or "Kimi"]
    if display.show_work_dir and state.work_dir:
        parts.append(state.work_dir)
    elif branch_name:
        parts.append(f"branch {branch_name}")
    parts.append(format_quota_reset(state))
    if state.membership:
        parts.append(state.membership)
    return _join(parts)


def _build_small_text(state: KimiState) -> str | None:
    mode = (state.agent_mode or "").strip().lower()
    effort = (state.reasoning_effort or "").strip()
    if mode == "agent":
        label = "Agent mode"
    elif mode in {"chat", ""}:
        label = "Chat mode" if mode else None
    else:
        label = f"{mode.capitalize()} mode"
    if label and effort:
        return f"{label} · {effort} effort"
    return label
