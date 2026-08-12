"""Mapping from Kimi's internal model keys to display names.

Keys are what Kimi Desktop writes into its own logs (``model_name=k2d6-agent``,
``applied global default model=...``). Unknown keys fall back to a tidied-up
version of the raw key rather than being dropped, so a new Kimi release still
shows something sensible.
"""

from __future__ import annotations

import re

DISPLAY_NAMES: dict[str, str] = {
    "k1-5": "Kimi K1.5",
    "k1.5": "Kimi K1.5",
    "kimi-k1.5": "Kimi K1.5",
    "k2-agent": "Kimi K2",
    "k2d6-agent": "Kimi K2.6",
    "k2d5-agent": "Kimi K2.5",
    "k3-agent": "Kimi K3",
    "k3-agent-ultra": "Kimi K3 Ultra",
    "k3-agent-swarm": "Kimi K3 Ultra",
    "kimi-vl": "Kimi VL",
    "moonshot-v1-8k": "Moonshot v1 8k",
    "moonshot-v1-32k": "Moonshot v1 32k",
    "moonshot-v1-128k": "Moonshot v1 128k",
}

# Agent modes Kimi reports alongside the model.
AGENT_MODE_LABELS: dict[str, str] = {
    "TYPE_NORMAL": "",
    "TYPE_ULTRA": "Ultra",
    "agent": "Agent",
    "chat": "Chat",
}

_TOKEN_SPLIT = re.compile(r"[-_]+")


def display_name(model_key: str | None) -> str | None:
    """Best-effort human name for a Kimi model key."""
    if not model_key:
        return None
    key = model_key.strip()
    if not key:
        return None
    known = DISPLAY_NAMES.get(key.lower())
    if known:
        return known
    return _prettify(key)


def _prettify(key: str) -> str:
    parts = [p for p in _TOKEN_SPLIT.split(key) if p]
    words = [p.upper() if len(p) <= 2 else p.capitalize() for p in parts]
    name = " ".join(words) if words else key
    if not name.lower().startswith("kimi"):
        name = f"Kimi {name}"
    return name


def format_context_window(tokens: int | None) -> str | None:
    """``262144`` -> ``256k ctx``; ``1000000`` -> ``1M ctx``."""
    if not tokens or tokens <= 0:
        return None
    if tokens >= 1_000_000:
        value = tokens / 1_000_000
        text = f"{value:.0f}M" if value == int(value) else f"{value:.1f}M"
    elif tokens >= 1024:
        value = tokens / 1024
        text = f"{value:.0f}k" if value == int(value) else f"{value:.1f}k"
    else:
        text = str(tokens)
    return f"{text} ctx"
