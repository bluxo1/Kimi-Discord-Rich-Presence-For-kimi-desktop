"""Thin wrapper around pypresence: connection lifecycle and rate limiting.

All traffic goes over Discord's local IPC socket (``discord-ipc-0``). No HTTP
requests are made, no tokens are read, and nothing is sent anywhere else.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .config import DISCORD_MIN_UPDATE_INTERVAL, BehaviourConfig
from .presence import PresencePayload

log = logging.getLogger(__name__)

try:
    from pypresence import Presence
    from pypresence.exceptions import PyPresenceException
except ImportError as exc:  # pragma: no cover - dependency is declared
    raise SystemExit(
        "pypresence is not installed. Run: pip install -r requirements.txt"
    ) from exc


class RichPresenceClient:
    """Connect lazily, retry with backoff, and never push faster than Discord allows."""

    def __init__(
        self,
        client_id: str,
        behaviour: BehaviourConfig | None = None,
        min_interval: int = DISCORD_MIN_UPDATE_INTERVAL,
    ) -> None:
        if not client_id or not client_id.strip():
            raise ValueError(
                "No Discord client id configured. Create an application at "
                "https://discord.com/developers/applications and put its "
                "Application ID in config.yaml under discord.client_id."
            )
        self.client_id = client_id.strip()
        self.behaviour = behaviour or BehaviourConfig()
        self.min_interval = max(min_interval, DISCORD_MIN_UPDATE_INTERVAL)

        self._rpc: Presence | None = None
        self._connected = False
        self._last_push = 0.0
        self._last_key: tuple | None = None
        self._cleared = False
        self._backoff = 1.0
        self._next_attempt = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Try to attach to a running Discord client. False if unavailable."""
        if self._connected:
            return True
        now = time.time()
        if now < self._next_attempt:
            return False
        try:
            self._rpc = Presence(self.client_id)
            self._rpc.connect()
        except (PyPresenceException, OSError, RuntimeError, ValueError) as exc:
            self._rpc = None
            self._connected = False
            self._schedule_retry()
            log.info("Discord not reachable (%s); retrying in %.0fs", type(exc).__name__, self._backoff)
            return False
        self._connected = True
        self._backoff = 1.0
        self._last_key = None
        self._cleared = False
        log.info("Connected to Discord IPC")
        return True

    def _schedule_retry(self) -> None:
        self._next_attempt = time.time() + self._backoff
        self._backoff = min(self._backoff * 2, float(self.behaviour.max_backoff))

    def _drop(self, exc: Exception) -> None:
        log.info("Discord connection lost (%s)", type(exc).__name__)
        self.close(clear=False)
        self._schedule_retry()

    def push(self, payload: PresencePayload, force: bool = False) -> bool:
        """Send ``payload`` if it changed and the rate limit allows it."""
        if not self.connect():
            return False

        now = time.time()
        unchanged = payload.key() == self._last_key
        if unchanged and not force:
            return False
        if not force and (now - self._last_push) < self.min_interval:
            return False

        kwargs: dict[str, Any] = payload.to_kwargs()
        if not kwargs:
            return self.clear()

        try:
            assert self._rpc is not None
            self._rpc.update(**kwargs)
        except (PyPresenceException, OSError, RuntimeError, BrokenPipeError) as exc:
            self._drop(exc)
            return False

        self._last_push = now
        self._last_key = payload.key()
        self._cleared = False
        log.debug("presence updated: %s", kwargs)
        return True

    def clear(self) -> bool:
        """Remove the presence card. No-op if it is already cleared."""
        if not self._connected or self._rpc is None or self._cleared:
            return False
        try:
            self._rpc.clear()
        except (PyPresenceException, OSError, RuntimeError, BrokenPipeError) as exc:
            self._drop(exc)
            return False
        self._last_key = None
        self._last_push = time.time()
        self._cleared = True
        return True

    def close(self, clear: bool = True) -> None:
        if self._rpc is not None:
            try:
                if clear and self._connected:
                    self._rpc.clear()
                self._rpc.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                log.debug("error while closing Discord connection", exc_info=True)
        self._rpc = None
        self._connected = False
        self._last_key = None

    def __enter__(self) -> RichPresenceClient:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
