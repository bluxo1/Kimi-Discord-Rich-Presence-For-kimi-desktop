"""Entry point: poll Kimi Desktop's local state and publish it to Discord."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .config import Settings, default_config_path, load_settings
from .git_reader import BranchInfo, branch_label, read_branch
from .kimi_detector import KimiDetector, KimiState
from .models import display_name, format_context_window
from .presence import PresencePayload, build_payload, format_elapsed, format_quota

log = logging.getLogger("kimi_discord_rpc")

_BRANCH_CACHE_TTL = 30.0


class _BranchCache:
    """Avoid walking up the filesystem on every poll."""

    def __init__(self, ttl: float = _BRANCH_CACHE_TTL) -> None:
        self.ttl = ttl
        self._dir: str | None = None
        self._info: BranchInfo | None = None
        self._at = 0.0

    def get(self, work_dir: str | None) -> BranchInfo | None:
        now = time.time()
        if work_dir != self._dir or (now - self._at) > self.ttl:
            self._dir = work_dir
            self._info = read_branch(work_dir)
            self._at = now
        return self._info


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pypresence").setLevel(logging.WARNING)


def _render(state: KimiState, payload: PresencePayload) -> str:
    """A terminal preview of the Discord card, for --dry-run / --once."""
    elapsed = None
    if state.session_started_at:
        elapsed = time.time() - state.session_started_at
    lines = [
        "  ┌─────────────────────────────────────────────┐",
        f"  │ {'Kimi AI':<43} │",
        f"  │ {(payload.details or '-')[:43]:<43} │",
        f"  │ {(payload.state or '-')[:43]:<43} │",
        f"  │ {('⏱  ' + format_elapsed(elapsed)) if elapsed else '⏱  --:--:--':<43} │",
        "  └─────────────────────────────────────────────┘",
        f"    hover: {payload.large_text or '-'}",
        f"    badge: {payload.small_text or '-'}",
    ]
    return "\n".join(lines)


def _doctor(settings: Settings) -> int:
    """Check every input this tool depends on and report what is missing."""
    detector = KimiDetector(settings.kimi)
    state = detector.poll()
    ok = True

    def line(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        mark = "OK  " if good else "MISS"
        print(f"  [{mark}] {label}" + (f" -- {detail}" if detail else ""))

    print(f"kimi-discord-rpc {__version__} diagnostics\n")
    print("Config")
    line(bool(settings.discord.client_id), "discord.client_id set",
         "create an app at discord.com/developers and paste its Application ID"
         if not settings.discord.client_id else settings.discord.client_id)

    print("\nKimi Desktop")
    log_path = detector.log_path
    line(log_path.is_file(), f"log file {log_path}")
    line(detector.tab_activity_path.is_file(), f"activity file {detector.tab_activity_path}")
    line(state.running, "Kimi Desktop process running")

    print("\nDetected state")
    print(f"    project       : {state.project_name or '(none - plain chat)'}")
    print(f"    work_dir      : {state.work_dir or '(none)'}")
    print(f"    model         : {display_name(state.model_key) or '(unknown)'} [{state.model_key or '-'}]")
    print(f"    context window: {format_context_window(state.context_window) or '(unknown)'}")
    print(f"    agent mode    : {state.agent_mode or '(unknown)'}")
    print(f"    quota         : {format_quota(state) or '(unknown)'}")
    branch = read_branch(state.work_dir)
    print(f"    git branch    : {branch_label(branch) or '(not a git repo / no work dir)'}")

    print("\nDiscord")
    try:
        from pypresence import Presence  # noqa: F401

        line(True, "pypresence installed")
    except ImportError:
        line(False, "pypresence installed", "pip install -r requirements.txt")

    print()
    return 0 if ok else 1


def _build_current(
    detector: KimiDetector, settings: Settings, branches: _BranchCache
) -> tuple[KimiState, PresencePayload]:
    state = detector.poll()
    branch = branches.get(state.work_dir) if settings.display.show_git_branch else None
    idle_for = state.idle_for()
    idle = idle_for is not None and idle_for > settings.display.idle_after
    payload = build_payload(
        state,
        settings.display,
        branch,
        large_image=settings.discord.large_image,
        small_image=settings.discord.small_image,
        buttons=settings.discord.buttons,
        idle=idle,
    )
    return state, payload


def run(settings: Settings, dry_run: bool = False, once: bool = False) -> int:
    detector = KimiDetector(settings.kimi)
    branches = _BranchCache()

    client = None
    if not dry_run:
        from .rpc_client import RichPresenceClient

        client = RichPresenceClient(
            settings.discord.client_id,
            settings.behaviour,
            settings.display.update_interval,
        )

    stop = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        log.info("shutting down (signal %s)", signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):  # pragma: no cover - not all platforms/threads
            pass

    log.info("watching %s", detector.log_path)

    try:
        while not stop:
            state, payload = _build_current(detector, settings, branches)

            if dry_run:
                print(_render(state, payload))
            elif client is not None:
                if not state.running and settings.behaviour.when_kimi_closed == "clear":
                    client.clear()
                else:
                    client.push(payload)

            if once:
                break
            for _ in range(settings.display.poll_interval):
                if stop:
                    break
                time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        if client is not None:
            client.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kimi-discord-rpc",
        description="Show your Kimi Desktop session on Discord Rich Presence.",
    )
    parser.add_argument("-c", "--config", type=Path, default=None,
                        help=f"path to config.yaml (default: {default_config_path()})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the presence card instead of sending it to Discord")
    parser.add_argument("--once", action="store_true",
                        help="do a single detection pass and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="check config, Kimi data files and detected state, then exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    try:
        settings = load_settings(args.config)
    except Exception as exc:  # noqa: BLE001 - config errors should be readable
        log.error("could not load configuration: %s", exc)
        return 2

    if args.doctor:
        return _doctor(settings)

    if not args.dry_run and not settings.discord.client_id:
        log.error(
            "discord.client_id is not set. Create an application at "
            "https://discord.com/developers/applications, copy its Application ID "
            "into config.yaml, then run again. Use --dry-run to preview without Discord."
        )
        return 2

    try:
        return run(settings, dry_run=args.dry_run, once=args.once)
    except ValueError as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
