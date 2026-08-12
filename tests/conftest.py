"""Shared fixtures: synthetic Kimi Desktop log lines.

The shapes here mirror what Kimi Desktop actually writes to
``%APPDATA%/kimi-desktop/logs/main.log``, including the sensitive fields the
parser is required to ignore.
"""

from __future__ import annotations

import json

import pytest

SECRET_QUERY = "please refactor the acquisition model spreadsheet"
SECRET_USER_ID = "test-user-000000000000"
SECRET_CHAT_ID = "conv-000000000000test"
SECRET_SEGMENT_ID = "00000000-0000-4000-8000-000000000000"


def send_message_line(
    *,
    timestamp: str = "2026-08-12 12:37:23.425",
    project_name: str = "demo-project",
    work_dir: str = "C:\\repos\\demo-project",
    is_in_project: bool = True,
    model_name: str = "k2d6-agent",
    context_window: int = 262144,
    agent_mode: str = "agent",
    reasoning_effort: str = "high",
    filename: str = "",
) -> str:
    """Build a ``kimi_work_send_message`` log line with secrets embedded."""
    payload = {
        "user_id": SECRET_USER_ID,
        "membership": "Free",
        "os_platform": "windows",
        "query": SECRET_QUERY,
        "filename": filename,
        "filetype": "",
        "work_dir": work_dir,
        "is_in_project": is_in_project,
        "project_name": project_name,
        "agent_mode": agent_mode,
        "is_first_message": True,
        "segment_id": SECRET_SEGMENT_ID,
        "model_name": model_name,
        "reasoning_effort": reasoning_effort,
        "context_window": context_window,
        "skills": [],
        "plugins": [],
        "permission_mode": "ask-permission",
        "chat_id": SECRET_CHAT_ID,
        "is_goal": False,
        "is_cron": False,
    }
    body = json.dumps([payload], separators=(",", ":"))
    return (
        f"[{timestamp}] [info]  \x1b[36m[VolcanoTracker]  "
        f"IPC received: action=kimi_work_send_message, args={body}, ready=true"
    )


SUBSCRIPTION_LINE = (
    "[2026-08-12 12:39:33.708] [info]  \x1b[36m[SubscriptionManager]  "
    "refreshed(sub): level=10 isMember=false omniRatio=0.04610000178217888 "
    "exhausted=false resetAt=2026-09-10T18:02:35.818Z"
)

MODEL_SYNC_LINE = (
    "[2026-08-12 12:14:36.435] [info]  \x1b[36m[KimiWorkModelSync]  "
    "sync(renderer-list-updated): applied global default model=k3-agent "
    "listChanged=true fromCache=false"
)

FOCUS_LINE = (
    "[2026-08-12 12:43:47.383] [info]  \x1b[36m[SurfaceReaper]  "
    "kimi tab activated (reason=window_focus); 24h reaper protection armed"
)

NAV_AGENT_LINE = (
    "[2026-08-12 12:43:05.007] [info]  \x1b[36m[LoadingFlow]  "
    "did-start-navigation url=https://www.kimi.com/agent?chat_enter_method=change_model "
    "isInPlace=true"
)

NAV_CHAT_LINE = (
    "[2026-08-12 12:43:05.005] [info]  \x1b[36m[LoadingFlow]  "
    "did-start-navigation url=https://www.kimi.com/chat/11111111-2222-4333-8444-555555555555"
    "?chat_enter_method=home isInPlace=true"
)

MULTILINE_CONFIG_LINES = [
    "[2026-08-12 12:41:21.180] [info]  \x1b[36m[KimiWorkModel]  describeKimiWorkConfig ok {",
    "  count: 3,",
    "  defaultModelKey: 'k2d6-agent',",
    "}",
]


@pytest.fixture()
def kimi_log(tmp_path):
    """A writable stand-in for Kimi's main.log."""
    path = tmp_path / "logs" / "main.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def append(path, *lines: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
