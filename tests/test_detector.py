from __future__ import annotations

import json

from conftest import (
    FOCUS_LINE,
    MODEL_SYNC_LINE,
    MULTILINE_CONFIG_LINES,
    NAV_AGENT_LINE,
    NAV_CHAT_LINE,
    SUBSCRIPTION_LINE,
    append,
    send_message_line,
)
from kimi_discord_rpc.config import KimiConfig
from kimi_discord_rpc.kimi_detector import (
    KimiDetector,
    LogTailer,
    extract_send_payload,
    parse_line_timestamp,
)


def _detector(log_path) -> KimiDetector:
    return KimiDetector(KimiConfig(log_file=log_path, tab_activity_file=log_path.parent / "missing.json"))


def test_tailer_yields_appended_lines_and_strips_ansi(kimi_log):
    tailer = LogTailer(kimi_log, bootstrap_bytes=0)
    assert list(tailer.poll()) == []

    append(kimi_log, MODEL_SYNC_LINE)
    lines = list(tailer.poll())
    assert len(lines) == 1
    assert "\x1b" not in lines[0]
    assert "applied global default model=k3-agent" in lines[0]

    assert list(tailer.poll()) == []


def test_tailer_handles_truncation(kimi_log):
    append(kimi_log, MODEL_SYNC_LINE, FOCUS_LINE)
    tailer = LogTailer(kimi_log, bootstrap_bytes=0)
    list(tailer.poll())

    # Kimi restarted and rewrote the log from scratch.
    kimi_log.write_text("", encoding="utf-8")
    append(kimi_log, SUBSCRIPTION_LINE)
    lines = list(tailer.poll())
    assert any("omniRatio" in line for line in lines)


def test_tailer_survives_missing_file(tmp_path):
    tailer = LogTailer(tmp_path / "nope.log")
    assert list(tailer.poll()) == []


def test_bootstrap_replays_the_tail(kimi_log):
    append(kimi_log, MODEL_SYNC_LINE, SUBSCRIPTION_LINE)
    tailer = LogTailer(kimi_log, bootstrap_bytes=1_000_000)
    lines = list(tailer.poll())
    assert len(lines) == 2


def test_parse_line_timestamp():
    assert parse_line_timestamp("[2026-08-12 12:37:23.425] [info] x") is not None
    assert parse_line_timestamp("  count: 3,") is None
    assert parse_line_timestamp("[not-a-date] hello") is None


def test_send_event_populates_state(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, send_message_line())
    state = detector.poll()

    assert state.project_name == "demo-project"
    assert state.work_dir == "C:\\repos\\demo-project"
    assert state.model_key == "k2d6-agent"
    assert state.context_window == 262144
    assert state.agent_mode == "agent"
    assert state.reasoning_effort == "high"
    assert state.last_message_at is not None


def test_plain_chat_clears_a_previous_project(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, send_message_line())
    assert detector.poll().project_name == "demo-project"

    append(kimi_log, send_message_line(project_name="", work_dir="", is_in_project=False))
    state = detector.poll()
    assert state.project_name is None
    assert state.work_dir is None
    # The model is remembered rather than cleared.
    assert state.model_key == "k2d6-agent"


def test_model_sync_line_sets_model(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, MODEL_SYNC_LINE)
    assert detector.poll().model_key == "k3-agent"


def test_subscription_line_sets_quota(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, SUBSCRIPTION_LINE)
    state = detector.poll()
    assert state.quota_used_ratio == 0.04610000178217888
    assert state.quota_exhausted is False
    assert state.quota_reset_at == "2026-09-10T18:02:35.818Z"
    assert state.membership == "Free"
    # The line's own timestamp, so the card can tell how cold the reading is.
    assert state.quota_updated_at == parse_line_timestamp(SUBSCRIPTION_LINE)


def test_navigation_sets_surface(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, NAV_AGENT_LINE)
    assert detector.poll().surface == "agent"
    append(kimi_log, NAV_CHAT_LINE)
    assert detector.poll().surface == "chat"


def test_multiline_records_are_ignored(kimi_log):
    detector = _detector(kimi_log)
    append(kimi_log, *MULTILINE_CONFIG_LINES)
    state = detector.poll()
    assert state.model_key is None
    assert state.project_name is None


def test_malformed_lines_do_not_raise(kimi_log):
    detector = _detector(kimi_log)
    append(
        kimi_log,
        "[2026-08-12 12:00:00.000] [info] IPC received: action=kimi_work_send_message, args=[{broken, ready=true",
        "[2026-08-12 12:00:01.000] [info] refreshed(sub): level=x omniRatio=zz",
        "",
        "\x00\x01 garbage",
    )
    detector.poll()  # must not raise


def test_extract_returns_none_for_unrelated_lines():
    assert extract_send_payload(FOCUS_LINE) is None
    assert extract_send_payload("") is None


def test_tab_activity_file_feeds_activity(tmp_path, kimi_log):
    activity = tmp_path / "kimi-tab-activity.json"
    activity.write_text(json.dumps({"activatedAt": 1786518964476}), encoding="utf-8")
    detector = KimiDetector(KimiConfig(log_file=kimi_log, tab_activity_file=activity))
    state = detector.poll()
    if state.running:  # only meaningful while Kimi is actually running
        assert state.last_activity_at is not None


def test_project_override_used_when_no_project(kimi_log):
    detector = KimiDetector(
        KimiConfig(
            log_file=kimi_log,
            tab_activity_file=kimi_log.parent / "missing.json",
            project_override="my-side-project",
        )
    )
    state = detector.poll()
    assert state.project_name == "my-side-project"
