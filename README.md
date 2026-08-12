# Kimi Desktop → Discord Rich Presence

Show your Kimi Desktop session on Discord: current project, git branch, model,
session time and quota usage — without touching credentials, without modifying
Kimi, and without sending anything anywhere except Discord's local IPC socket.

```
┌─────────────────────────────────────────────┐
│ Kimi AI                                     │
│ 📁 my-api-refactor · 🌿 feat/auth-v2         │
│ 🧠 Kimi K2.6 · 256k ctx · 7.8% quota used    │
│ ⏱  00:42:18                                 │
└─────────────────────────────────────────────┘
```

## How it detects things

Kimi Desktop is an Electron app that writes structured events to its own log at
`%APPDATA%\kimi-desktop\logs\main.log`. That log is the data source — it is
richer and far safer than scraping window titles or intercepting traffic:

| Field | Source |
| --- | --- |
| Project name, working directory | `IPC received: action=kimi_work_send_message` payload |
| Model, agent mode, context window | same payload, plus `[KimiWorkModelSync] applied global default model=` |
| Quota used, reset date, plan | `[SubscriptionManager] refreshed(sub): omniRatio=…` |
| Session time | Kimi Desktop's process start time (via `psutil`) |
| Focus / activity | `[SurfaceReaper] kimi tab activated`, `[LoadingFlow] did-start-navigation` |
| Git branch | `.git/HEAD` under the working directory, parsed directly |

Two deliberate deviations from the obvious approach:

* **Window titles are not used.** Kimi Desktop's window title is the constant
  string `kimi-desktop` — it carries no project or model information.
* **No traffic interception.** See the note on token counts below.

## Token counts and cost: what is actually available

Kimi Desktop does not write per-message token counts or costs anywhere on the
local machine. Getting real `prompt_tokens` / `completion_tokens` numbers out of
the desktop app would mean man-in-the-middling its HTTPS traffic with a local
proxy and a trusted root certificate — which contradicts the security rules this
tool is built around, and would put you one bug away from logging your own
prompts and session cookies to disk.

So instead of inventing a number, this tool shows the usage signal Kimi *does*
publish locally: **the share of your account quota consumed** (`omniRatio`),
its reset date, and the model's context window. If you want true token
accounting, use the Moonshot API directly with your own key — the API returns a
`usage` block per response, and that is the only honest place to get it.

## Install

```bash
git clone <your-repo> kimi-discord-rpc
cd kimi-discord-rpc
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
```

## Discord app setup

1. Open <https://discord.com/developers/applications> → **New Application**, name it `Kimi AI`.
2. **Rich Presence → Art Assets**: upload your Kimi logo with the asset key `kimi_logo`.
3. Copy the **Application ID** from *General Information*.
4. Paste it into `config.yaml` as `discord.client_id`.

No bot token, no OAuth secret and no scopes are involved. The Application ID is
a public identifier.

In Discord itself: **Settings → Activity Privacy → Share your detected
activities with others** must be on, or nothing will show.

## Run

```bash
python -m kimi_discord_rpc --doctor      # check config, data files, detected state
python -m kimi_discord_rpc --dry-run     # print the card instead of publishing it
python -m kimi_discord_rpc               # publish to Discord
```

`--doctor` is the first thing to run if something looks wrong: it prints every
input path, whether Kimi is running, and exactly what was detected.

## Configuration

Everything lives in `config.yaml`, and every key can be overridden from the
environment with the `KIMI_RPC_` prefix and `__` for nesting:

```bash
KIMI_RPC_DISCORD__CLIENT_ID=123456789012345678
KIMI_RPC_DISPLAY__SHOW_GIT_BRANCH=false
```

Privacy-relevant switches, all **off** by default:

| Key | Effect |
| --- | --- |
| `display.show_work_dir` | puts the absolute working directory in the hover text |
| `display.show_file` | puts the open filename on the card |

`display.update_interval` is clamped up to 15 seconds because Discord throttles
presence updates at roughly that rate; lower values just get dropped.

## Security posture

* **No credentials, ever.** The tool never reads Discord tokens, Kimi API keys,
  cookie jars or session storage. Kimi's `Network/Cookies` database sits right
  next to the log it reads and is never opened.
* **Whitelist parsing.** Kimi's send-message log line also contains your prompt
  text, user id and chat id. `PAYLOAD_WHITELIST` in `kimi_detector.py` is the
  complete set of keys the parser will copy; everything else is dropped at parse
  time. `tests/test_privacy.py` asserts that prompt text and identifiers cannot
  reach the Discord payload under any display configuration.
* **Read-only.** Files are opened for reading only. Nothing is injected into the
  Kimi process, no DLLs, no hooks, no proxying.
* **Local only.** The single outbound channel is Discord's named pipe
  (`discord-ipc-0`). No HTTP requests, no telemetry, no analytics, no listeners
  and no open ports.
* **No shelling out to git.** The branch comes from parsing `.git/HEAD`, so
  shell injection is not in the threat model at all.
* **User-level.** No administrator rights are needed or requested.

## Packaging

```bash
pip install pyinstaller
pyinstaller kimi-discord-rpc.spec
```

The binary lands in `dist/`. It reads `config.yaml` from the working directory,
so keep the two together.

To start it with Windows, put a shortcut to the executable in:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

## Tests

```bash
python -m pytest -q
```

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `Client ID is Invalid` | `discord.client_id` is wrong or still a placeholder |
| Nothing appears, no errors | Activity Privacy is off in Discord settings, or the Discord *desktop* app is not running (the web client has no IPC socket) |
| Card shows "Chatting with Kimi" | Kimi reports no project — it is a plain chat, not a project session. Set `kimi.project_override` if you want a fixed name |
| No git branch | The Kimi session has no working directory, or it is not inside a repository |
| Model shows a raw key | New Kimi release; add it to `DISPLAY_NAMES` in `models.py` |

## License

MIT — see [LICENSE](LICENSE).
