from __future__ import annotations

import time

from kimi_discord_rpc.config import DisplayConfig, Settings, load_settings
from kimi_discord_rpc.git_reader import BranchInfo
from kimi_discord_rpc.kimi_detector import KimiState
from kimi_discord_rpc.models import display_name, format_context_window
from kimi_discord_rpc.presence import (
    MAX_FIELD,
    build_payload,
    format_elapsed,
    format_quota,
)


def _state(**kwargs) -> KimiState:
    base = dict(
        running=True,
        project_name="my-api-refactor",
        work_dir="C:\\repos\\my-api-refactor",
        model_key="k2d6-agent",
        context_window=262144,
        agent_mode="agent",
        quota_used_ratio=0.046,
        quota_reset_at="2026-09-10T18:02:35.818Z",
        session_started_at=time.time() - 2538,
    )
    base.update(kwargs)
    return KimiState(**base)


def _branch(name="feat/auth-v2") -> BranchInfo:
    from pathlib import Path

    return BranchInfo(name=name, detached=False, git_dir=Path("."))


def test_full_card():
    card = build_payload(_state(), DisplayConfig(), _branch())
    assert "my-api-refactor" in card.details
    assert "feat/auth-v2" in card.details
    assert "Kimi K2.6" in card.state
    assert "256k ctx" in card.state
    assert "4.6% quota used" in card.state
    assert card.start is not None


def test_card_without_project_falls_back_to_chatting():
    card = build_payload(_state(project_name=None, surface="chat"), DisplayConfig(), None)
    assert "Chatting with Kimi" in card.details


def test_agent_surface_without_project():
    card = build_payload(_state(project_name=None, surface="agent"), DisplayConfig(), None)
    assert "Kimi Agent" in card.details


def test_not_running_shows_idle_only():
    card = build_payload(KimiState(running=False), DisplayConfig(), None)
    assert card.details == "Idle"
    assert card.state is None
    assert card.start is None


def test_toggles_remove_fields():
    display = DisplayConfig(
        show_git_branch=False,
        show_model=False,
        show_quota=False,
        show_context_window=False,
        show_session_timer=False,
    )
    card = build_payload(_state(), display, _branch())
    assert "feat/auth-v2" not in (card.details or "")
    assert card.state is None
    assert card.start is None


def test_fields_are_clamped_to_discord_limits():
    card = build_payload(_state(project_name="x" * 400), DisplayConfig(), _branch("y" * 400))
    assert len(card.details) <= MAX_FIELD
    assert len(card.state or "") <= MAX_FIELD


def test_idle_flag_shows_idle_badge():
    card = build_payload(_state(), DisplayConfig(), None, idle=True)
    assert card.small_text == "Idle"


def test_payload_key_changes_with_content():
    a = build_payload(_state(), DisplayConfig(), None)
    b = build_payload(_state(project_name="other"), DisplayConfig(), None)
    assert a.key() != b.key()


def test_to_kwargs_omits_empty_fields():
    card = build_payload(KimiState(running=False), DisplayConfig(), None)
    kwargs = card.to_kwargs()
    assert "state" not in kwargs
    assert "start" not in kwargs


def test_quota_formatting():
    assert format_quota(_state(quota_used_ratio=0.046)) == "4.6% quota used"
    assert format_quota(_state(quota_used_ratio=0.5)) == "50% quota used"
    assert format_quota(_state(quota_exhausted=True)) == "quota exhausted"
    assert format_quota(_state(quota_used_ratio=None)) is None


def test_elapsed_formatting():
    assert format_elapsed(2538) == "00:42:18"
    assert format_elapsed(None) == "--:--:--"
    assert format_elapsed(-5) == "--:--:--"


def test_model_names():
    assert display_name("k2d6-agent") == "Kimi K2.6"
    assert display_name("k3-agent-swarm") == "Kimi K3 Ultra"
    assert display_name("kimi-vl") == "Kimi VL"
    assert display_name("k9-mystery") == "Kimi K9 Mystery"
    assert display_name(None) is None


def test_context_window_formatting():
    assert format_context_window(262144) == "256k ctx"
    assert format_context_window(1_000_000) == "1M ctx"
    assert format_context_window(None) is None


def test_update_interval_is_clamped_to_discord_floor():
    assert DisplayConfig(update_interval=1).update_interval == 15


def test_config_file_round_trip(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "discord:\n  client_id: '123'\ndisplay:\n  show_git_branch: false\n",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.discord.client_id == "123"
    assert settings.display.show_git_branch is False


def test_environment_overrides_the_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("discord:\n  client_id: 'from-file'\n", encoding="utf-8")
    monkeypatch.setenv("KIMI_RPC_DISCORD__CLIENT_ID", "from-env")
    settings = load_settings(path)
    assert settings.discord.client_id == "from-env"


def test_missing_config_file_is_fine(tmp_path):
    assert isinstance(load_settings(tmp_path / "absent.yaml"), Settings)
