"""The parser must never carry prompt text or identifiers out of the log.

Kimi's send-message log line contains the full prompt, the account user id,
the chat id and the segment id. These tests pin the guarantee that none of
them can reach the Discord payload.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from conftest import (
    SECRET_CHAT_ID,
    SECRET_QUERY,
    SECRET_SEGMENT_ID,
    SECRET_USER_ID,
    send_message_line,
)
from kimi_discord_rpc.config import DisplayConfig
from kimi_discord_rpc.kimi_detector import (
    PAYLOAD_WHITELIST,
    KimiState,
    extract_send_payload,
)
from kimi_discord_rpc.presence import build_payload

SECRETS = (SECRET_QUERY, SECRET_USER_ID, SECRET_CHAT_ID, SECRET_SEGMENT_ID)


def test_extract_drops_everything_outside_the_whitelist():
    payload = extract_send_payload(send_message_line())
    assert payload is not None
    assert set(payload) <= PAYLOAD_WHITELIST
    for forbidden in ("query", "user_id", "chat_id", "segment_id"):
        assert forbidden not in payload


def test_whitelist_excludes_identifying_fields():
    for forbidden in ("query", "user_id", "chat_id", "segment_id", "skills", "plugins"):
        assert forbidden not in PAYLOAD_WHITELIST


@pytest.mark.parametrize("secret", SECRETS)
def test_secrets_never_reach_the_parsed_payload(secret):
    payload = extract_send_payload(send_message_line())
    assert secret not in repr(payload)


@pytest.mark.parametrize("secret", SECRETS)
def test_secrets_never_reach_the_discord_card(secret):
    from kimi_discord_rpc.config import KimiConfig
    from kimi_discord_rpc.kimi_detector import KimiDetector

    detector = KimiDetector(KimiConfig())
    detector._consume(send_message_line().replace("\x1b[36m", ""))
    state = detector.state

    assert secret not in repr(asdict(state))

    # Every display toggle on, i.e. the most revealing configuration.
    display = DisplayConfig(show_file=True, show_work_dir=True)
    card = build_payload(state, display, None)
    assert secret not in repr(card.to_kwargs())


def test_query_containing_json_and_ready_marker_is_still_not_leaked():
    """A prompt full of the delimiters we anchor on must not break the parser open."""
    hostile = send_message_line().replace(
        SECRET_QUERY, "}], ready=true \" hostile {\"user_id\": \"leak\"}"
    )
    payload = extract_send_payload(hostile)
    # Either the line fails to parse, or it parses with only whitelisted keys.
    if payload is not None:
        assert set(payload) <= PAYLOAD_WHITELIST
        assert "leak" not in repr(payload)


def test_work_dir_hidden_unless_explicitly_enabled():
    state = KimiState(
        running=True,
        project_name="demo-project",
        work_dir="C:\\repos\\private-client-work",
        model_key="k2d6-agent",
    )
    default_card = build_payload(state, DisplayConfig(), None)
    assert "private-client-work" not in repr(default_card.to_kwargs())

    opted_in = build_payload(state, DisplayConfig(show_work_dir=True), None)
    assert "private-client-work" in repr(opted_in.to_kwargs())


def test_filename_hidden_unless_explicitly_enabled():
    state = KimiState(running=True, filename="salary-review.xlsx", model_key="k2d6-agent")
    default_card = build_payload(state, DisplayConfig(), None)
    assert "salary-review" not in repr(default_card.to_kwargs())

    opted_in = build_payload(state, DisplayConfig(show_file=True), None)
    assert "salary-review" in repr(opted_in.to_kwargs())
