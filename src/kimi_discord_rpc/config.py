"""Configuration: YAML file with environment-variable overrides.

Environment overrides use the ``KIMI_RPC_`` prefix and ``__`` for nesting,
e.g. ``KIMI_RPC_DISCORD__CLIENT_ID=123``, ``KIMI_RPC_DISPLAY__SHOW_GIT_BRANCH=false``.
Environment values win over the YAML file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Discord throttles presence updates to roughly one per 15 seconds. Going
# faster does not get you a faster update, it just gets the payload dropped.
DISCORD_MIN_UPDATE_INTERVAL = 15


class DiscordConfig(BaseModel):
    client_id: str = ""
    large_image: str = "kimi_logo"
    small_image: str = ""
    # Buttons are optional; Discord allows at most two.
    buttons: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("buttons")
    @classmethod
    def _at_most_two(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(v) > 2:
            raise ValueError("Discord allows at most 2 presence buttons")
        for button in v:
            if set(button) != {"label", "url"}:
                raise ValueError("each button needs exactly 'label' and 'url'")
            if not button["url"].startswith(("http://", "https://")):
                raise ValueError("button urls must be http(s)")
        return v


class KimiConfig(BaseModel):
    """Where to observe Kimi Desktop from. All paths are read-only inputs."""

    # Left empty means "work it out from the platform default".
    data_dir: Path | None = None
    log_file: Path | None = None
    tab_activity_file: Path | None = None
    process_names: list[str] = Field(default_factory=lambda: ["Kimi", "kimi-desktop"])
    # How much of the tail of the log to replay on startup, so the presence is
    # correct immediately instead of after the next Kimi event.
    bootstrap_bytes: int = 262_144
    # Manual fallback when Kimi reports no project (plain chat sessions).
    project_override: str = ""

    def resolved_data_dir(self) -> Path:
        if self.data_dir is not None:
            return self.data_dir
        return default_kimi_data_dir()

    def resolved_log_file(self) -> Path:
        if self.log_file is not None:
            return self.log_file
        return self.resolved_data_dir() / "logs" / "main.log"

    def resolved_tab_activity_file(self) -> Path:
        if self.tab_activity_file is not None:
            return self.tab_activity_file
        return self.resolved_data_dir() / "bridge-store" / "kimi-tab-activity.json"


class DisplayConfig(BaseModel):
    show_project: bool = True
    show_git_branch: bool = True
    show_model: bool = True
    show_session_timer: bool = True
    # Kimi Desktop does not expose per-message token counts locally, so this
    # shows the account quota consumed so far instead. See README.
    show_quota: bool = True
    show_context_window: bool = True
    # The working directory / open filename can be identifying. Off by default.
    show_file: bool = False
    show_work_dir: bool = False
    idle_text: str = "Idle"
    chatting_text: str = "Chatting with Kimi"
    # Seconds between presence pushes. Clamped up to the Discord minimum.
    update_interval: int = DISCORD_MIN_UPDATE_INTERVAL
    # Seconds between local state polls (cheap; no network).
    poll_interval: int = 5
    # Drop back to an idle presence after this long with no Kimi activity.
    idle_after: int = 900

    @field_validator("update_interval")
    @classmethod
    def _respect_discord_floor(cls, v: int) -> int:
        return max(v, DISCORD_MIN_UPDATE_INTERVAL)

    @field_validator("poll_interval")
    @classmethod
    def _sane_poll(cls, v: int) -> int:
        return max(v, 1)


class BehaviourConfig(BaseModel):
    # If Kimi is not running: clear the presence, or show an idle card.
    when_kimi_closed: Literal["clear", "idle"] = "clear"
    # Keep trying to reach Discord forever, with backoff.
    reconnect: bool = True
    max_backoff: int = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KIMI_RPC_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    kimi: KimiConfig = Field(default_factory=KimiConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    behaviour: BehaviourConfig = Field(default_factory=BehaviourConfig)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):  # noqa: D102
        # Environment ahead of init args, so env overrides the YAML file that
        # load_settings() passes in as init args.
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)


def default_kimi_data_dir() -> Path:
    """Per-platform location of Kimi Desktop's Electron user-data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "kimi-desktop"
        return Path.home() / "AppData" / "Roaming" / "kimi-desktop"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kimi-desktop"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "kimi-desktop"


def default_config_path() -> Path:
    """The config to use when none was named on the command line.

    ``config.local.yaml`` is gitignored and holds your own Discord Application
    ID, so it wins over the checked-in ``config.yaml`` template when present.
    """
    local = Path.cwd() / "config.local.yaml"
    if local.is_file():
        return local
    return Path.cwd() / "config.yaml"


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from ``config_path`` (if it exists) plus the environment."""
    data: dict[str, Any] = {}
    path = config_path or default_config_path()
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} must contain a YAML mapping at the top level")
            data = loaded
    return Settings(**data)
