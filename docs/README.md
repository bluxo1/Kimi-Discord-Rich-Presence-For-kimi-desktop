# docs/ — project website

A single static page. No build step, no dependencies, no external requests:
open `index.html` in a browser and it works.

* `index.html` — the whole site (markup, CSS and script inline)
* `kimi_logo.png` — copy of `assets/kimi_logo.png`, used as artwork and favicon

The interactive card in the "Everything on the card is a switch" section mirrors
`build_payload()` in [`src/kimi_discord_rpc/presence.py`](../src/kimi_discord_rpc/presence.py):
the same priority order, the same fallbacks (project → agent → chat), the same
128-character clamp, and the same rule that `show_file` replaces the context
window on line two. If that function changes, update the `build()` function near
the bottom of `index.html` to match.

## Publishing

GitHub → **Settings → Pages → Source: Deploy from a branch**, branch `main`,
folder `/docs`. The site is then served at
<https://bluxo1.github.io/Kimi-Discord-Rich-Presence-For-kimi-desktop/>.
