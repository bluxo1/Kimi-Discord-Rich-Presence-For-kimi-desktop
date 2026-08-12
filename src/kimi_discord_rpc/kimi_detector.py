"""Observe Kimi Desktop's local state.

Strictly read-only: this module opens Kimi's own log and state files for
reading and inspects process metadata. It never writes to, injects into, or
proxies traffic for the Kimi process.

Everything is extracted from Kimi Desktop's Electron main log, which records
structured events as the app runs:

* ``IPC received: action=kimi_work_send_message, args=[{...}]`` -- carries the
  project name, working directory, model, agent mode and context window.
* ``[KimiWorkModelSync] ... applied global default model=<key>`` -- the model
  in use when no message has been sent yet.
* ``[SubscriptionManager] refreshed(sub): ... omniRatio=<0..1> ...`` -- how
  much of the account quota is consumed.
* ``[SurfaceReaper] kimi tab activated (reason=...)`` -- focus events.
* ``[LoadingFlow] did-start-navigation url=...`` -- which surface is open.

The send-message payload also contains the prompt text, a user id and a chat
id. Those are deliberately never read out of it: :data:`PAYLOAD_WHITELIST` is
the complete set of keys this module will copy, and everything else in the
payload is dropped at parse time.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import KimiConfig

log = logging.getLogger(__name__)

try:  # psutil is optional; without it we fall back to log freshness.
    import psutil
except ImportError:  # pragma: no cover - exercised only on minimal installs
    psutil = None  # type: ignore[assignment]

# The only keys ever copied out of Kimi's send-message payload. Notably absent:
# query, user_id, chat_id, segment_id.
PAYLOAD_WHITELIST: frozenset[str] = frozenset(
    {
        "project_name",
        "work_dir",
        "is_in_project",
        "model_name",
        "agent_mode",
        "reasoning_effort",
        "context_window",
        "membership",
        "filename",
        "filetype",
    }
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?\]")
_SEND_MARKER = "IPC received: action=kimi_work_send_message"
_ARGS_MARKER = "args="
_READY_MARKER = ", ready="
_MODEL_APPLIED = re.compile(r"applied global default model=([\w.+-]+)")
_SUBSCRIPTION = re.compile(
    r"refreshed\(sub\):\s*level=(?P<level>\d+)\s+isMember=(?P<member>\w+)\s+"
    r"omniRatio=(?P<ratio>[\d.eE+-]+)\s+exhausted=(?P<exhausted>\w+)\s+"
    r"resetAt=(?P<reset>\S+)"
)
_TAB_ACTIVATED = re.compile(r"kimi tab activated \(reason=(\w+)\)")
_NAVIGATION = re.compile(r"did-start-navigation url=(?P<url>\S+)")
# Surface, not chat id: we only care whether it is the agent or a chat.
_AGENT_SURFACE = re.compile(r"^https://[^/]+/agent\b")
_CHAT_SURFACE = re.compile(r"^https://[^/]+/chat/")

_MAX_TEXT_FIELD = 120


@dataclass
class KimiState:
    """Everything the presence layer is allowed to know about the session."""

    running: bool = False
    project_name: str | None = None
    work_dir: str | None = None
    filename: str | None = None
    filetype: str | None = None
    model_key: str | None = None
    agent_mode: str | None = None
    reasoning_effort: str | None = None
    context_window: int | None = None
    membership: str | None = None
    surface: str | None = None  # "agent" | "chat"
    quota_used_ratio: float | None = None
    quota_exhausted: bool = False
    quota_reset_at: str | None = None
    session_started_at: float | None = None
    last_message_at: float | None = None
    last_activity_at: float | None = None

    def idle_for(self, now: float | None = None) -> float | None:
        if self.last_activity_at is None:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.last_activity_at)

    def key(self) -> tuple:
        """Identity used to decide whether the presence actually changed."""
        return (
            self.running,
            self.project_name,
            self.filename,
            self.model_key,
            self.agent_mode,
            self.context_window,
            self.surface,
            None if self.quota_used_ratio is None else round(self.quota_used_ratio, 4),
            self.quota_exhausted,
            self.session_started_at,
        )


def _clean(value: Any) -> str | None:
    """Coerce a payload value to a short, single-line string (or ``None``)."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = value.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return None
    return text[:_MAX_TEXT_FIELD]


def parse_line_timestamp(line: str) -> float | None:
    """Epoch seconds for a log line's leading local timestamp."""
    match = _TIMESTAMP.match(line)
    if not match:
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    millis = int(match.group(2) or 0)
    return stamp.timestamp() + millis / 1000.0


def extract_send_payload(line: str) -> dict[str, Any] | None:
    """Pull the whitelisted fields out of a ``kimi_work_send_message`` line.

    Returns ``None`` for any line that is not such an event or whose payload
    cannot be parsed. The prompt text and identifiers present in the raw
    payload are never returned.
    """
    marker = line.find(_SEND_MARKER)
    if marker == -1:
        return None
    args_start = line.find(_ARGS_MARKER, marker)
    if args_start == -1:
        return None
    body_start = args_start + len(_ARGS_MARKER)
    # The prompt itself can contain almost anything, so anchor on the trailing
    # ", ready=" that Kimi appends after the argument array.
    body_end = line.rfind(_READY_MARKER)
    body = line[body_start:body_end] if body_end > body_start else line[body_start:]
    body = body.strip()
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, list):
        parsed = next((item for item in parsed if isinstance(item, dict)), None)
    if not isinstance(parsed, dict):
        return None
    return {k: v for k, v in parsed.items() if k in PAYLOAD_WHITELIST}


class LogTailer:
    """Yield new complete lines appended to a growing log file.

    Handles the file being absent, replaced or truncated between polls, which
    is what happens when Kimi Desktop restarts or rotates its log.
    """

    def __init__(self, path: Path, bootstrap_bytes: int = 262_144) -> None:
        self.path = Path(path)
        self.bootstrap_bytes = max(0, bootstrap_bytes)
        self._pos: int | None = None
        self._buffer = b""

    def reset(self) -> None:
        self._pos = None
        self._buffer = b""

    def poll(self) -> Iterator[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            self.reset()
            return

        if self._pos is None:
            # First read: replay a slice of the tail so state is correct now.
            self._pos = max(0, size - self.bootstrap_bytes)
        elif size < self._pos:
            # Truncated or replaced -- start over from the beginning.
            log.debug("kimi log shrank (%s -> %s); rereading", self._pos, size)
            self._pos = 0
            self._buffer = b""
        elif size == self._pos:
            return

        try:
            with self.path.open("rb") as handle:
                handle.seek(self._pos)
                chunk = handle.read()
                self._pos = handle.tell()
        except OSError as exc:
            log.debug("could not read kimi log: %s", exc)
            return

        data = self._buffer + chunk
        *lines, self._buffer = data.split(b"\n")
        # A partial first line after a mid-file bootstrap seek is discarded by
        # virtue of starting at an arbitrary offset; timestamp parsing rejects it.
        for raw in lines:
            text = raw.decode("utf-8", errors="replace").rstrip("\r")
            if text:
                yield _ANSI.sub("", text)


class KimiDetector:
    """Builds a :class:`KimiState` from Kimi Desktop's local files."""

    def __init__(self, config: KimiConfig) -> None:
        self.config = config
        self.log_path = config.resolved_log_file()
        self.tab_activity_path = config.resolved_tab_activity_file()
        self.tailer = LogTailer(self.log_path, config.bootstrap_bytes)
        self.state = KimiState()
        self._first_seen_running: float | None = None

    # -- individual line handlers -------------------------------------------------

    def _apply_send_event(self, payload: dict[str, Any], when: float | None) -> None:
        state = self.state
        if payload.get("is_in_project"):
            state.project_name = _clean(payload.get("project_name")) or state.project_name
            state.work_dir = _clean(payload.get("work_dir")) or state.work_dir
        else:
            project = _clean(payload.get("project_name"))
            work_dir = _clean(payload.get("work_dir"))
            # A plain chat clears any previously detected project.
            state.project_name = project
            state.work_dir = work_dir
        state.filename = _clean(payload.get("filename"))
        state.filetype = _clean(payload.get("filetype"))
        state.model_key = _clean(payload.get("model_name")) or state.model_key
        state.agent_mode = _clean(payload.get("agent_mode")) or state.agent_mode
        state.reasoning_effort = _clean(payload.get("reasoning_effort"))
        state.membership = _clean(payload.get("membership")) or state.membership
        context = payload.get("context_window")
        if isinstance(context, int) and context > 0:
            state.context_window = context
        if when is not None:
            state.last_message_at = when
            state.last_activity_at = max(when, state.last_activity_at or 0.0)

    def _apply_subscription(self, match: re.Match[str]) -> None:
        state = self.state
        try:
            state.quota_used_ratio = float(match.group("ratio"))
        except (TypeError, ValueError):
            state.quota_used_ratio = None
        state.quota_exhausted = match.group("exhausted").lower() == "true"
        state.quota_reset_at = match.group("reset")
        if state.membership is None:
            state.membership = "Member" if match.group("member").lower() == "true" else "Free"

    def _apply_navigation(self, url: str) -> None:
        if _AGENT_SURFACE.match(url):
            self.state.surface = "agent"
        elif _CHAT_SURFACE.match(url):
            self.state.surface = "chat"

    def _consume(self, line: str) -> None:
        when = parse_line_timestamp(line)
        if when is None:
            # Continuation line of a multi-line log record; nothing to do.
            return

        payload = extract_send_payload(line)
        if payload is not None:
            self._apply_send_event(payload, when)
            return

        model = _MODEL_APPLIED.search(line)
        if model:
            self.state.model_key = model.group(1)
            return

        subscription = _SUBSCRIPTION.search(line)
        if subscription:
            self._apply_subscription(subscription)
            return

        if _TAB_ACTIVATED.search(line):
            self.state.last_activity_at = max(when, self.state.last_activity_at or 0.0)
            return

        navigation = _NAVIGATION.search(line)
        if navigation:
            self._apply_navigation(navigation.group("url"))
            self.state.last_activity_at = max(when, self.state.last_activity_at or 0.0)

    # -- process / session ---------------------------------------------------------

    def _process_session_start(self) -> tuple[bool, float | None]:
        """(running, earliest process start time) for Kimi Desktop."""
        if psutil is None:
            return self._session_start_fallback()
        wanted = {name.lower() for name in self.config.process_names}
        earliest: float | None = None
        for proc in psutil.process_iter(["name", "create_time"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name.endswith(".exe"):
                    name = name[: -len(".exe")]
                if name not in wanted:
                    continue
                created = proc.info.get("create_time")
                if created and (earliest is None or created < earliest):
                    earliest = created
            except (psutil.NoSuchProcess, psutil.AccessDenied):  # pragma: no cover
                continue
        return earliest is not None, earliest

    def _session_start_fallback(self) -> tuple[bool, float | None]:
        """Without psutil, treat a recently-written log as "Kimi is running"."""
        try:
            modified = self.log_path.stat().st_mtime
        except OSError:
            return False, None
        running = (time.time() - modified) < 600
        if running and self._first_seen_running is None:
            self._first_seen_running = time.time()
        if not running:
            self._first_seen_running = None
        return running, self._first_seen_running

    def _read_tab_activation(self) -> float | None:
        try:
            raw = self.tab_activity_path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        activated = data.get("activatedAt") if isinstance(data, dict) else None
        if isinstance(activated, (int, float)) and activated > 0:
            return float(activated) / 1000.0
        return None

    # -- public API ----------------------------------------------------------------

    def poll(self) -> KimiState:
        """Refresh and return the current state. Never raises for missing files."""
        for line in self.tailer.poll():
            try:
                self._consume(line)
            except Exception:  # pragma: no cover - a bad line must not kill the loop
                log.debug("failed to parse kimi log line", exc_info=True)

        running, session_start = self._process_session_start()
        self.state.running = running
        self.state.session_started_at = session_start if running else None

        activated = self._read_tab_activation()
        if activated is not None:
            self.state.last_activity_at = max(activated, self.state.last_activity_at or 0.0)

        if not running:
            self.tailer.reset()
            self.state.last_activity_at = None

        if self.config.project_override and not self.state.project_name:
            self.state.project_name = _clean(self.config.project_override)

        return self.state
