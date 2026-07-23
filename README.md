**English** | [繁體中文](README.zh-TW.md)

# asktop

An htop that "can see the network and can ask an AI" — it integrates process monitoring, per-process network traffic, and port usage into a single TUI, and lets you ask "what's going on with the system right now?" in natural language.

**Status: v0.1.0 — Phases 1–3 implemented, Phase 4 started** (process table / global traffic / per-process traffic / ports tab / setup wizard / AI querying; macOS per-process traffic is now official).
What remains are the other non-committed Phase 4 items from PLAN.md §6. Per-process traffic: Linux needs root + nethogs, macOS uses the built-in `nettop` (no root required).

```bash
uv sync
sudo .venv/bin/python asktop.py        # sudo by default; without root it degrades (behavior differs per platform)
sudo .venv/bin/python asktop.py setup  # re-run the setup wizard
```

**Do not use `sudo uv run`** — it leaves root-owned files in `.venv`/cache, and later a normal-account `uv sync` will hit permission errors.

For the full planning document see [PLAN.md](./PLAN.md) (produced by the Fable5 model, 2026-07-21); for the change log see [CHANGELOG.md](./CHANGELOG.md).

## Architecture and files

| File | Description |
|---|---|
| `asktop.py` | UI and main loop (Textual). Three tabs: Process / Ports / AI |
| `collectors.py` | System data collection + the compressed system summary used by the AI. **Does not import textual** |
| `mask.py` | cmdline secret masking. Pure functions, zero dependencies |
| `tools.py` | The AI's six read-only tools and their schemas. **Does not import textual** |
| `llm.py` | OpenRouter streaming client and agent loop. **Does not import textual** |
| `config.py` | Config read/write, including sudo home-directory resolution |
| `wizard.py` | First-run setup wizard |
| `spike/` | Verification scripts (no test framework; plain asserts + `✓/✗`, exit 1 on failure) |

Separating the UI layer from the collection layer is deliberate: Textual carries breaking-change risk, and data collection should not be tied to it.

```bash
for t in mask llm summary tools ai_ui wizard; do .venv/bin/python spike/test_$t.py; done
```

## AI querying

After setting a model and API key (steps 2 and 3 of the wizard, or the `ASKTOP_API_KEY` environment variable), the AI tab lets you ask about system state in natural language.

- **A small summary as a baseline + six read-only tools for on-demand deep dives**: `get_top_processes`, `get_process_detail`, `get_connections`, `get_listening_ports`, `get_net_rates`, `search_process`
- **The AI has no write or kill capability** — it only investigates and advises; destructive operations are always confirmed and executed by a human in the UI
- **cmdline is always masked before being sent** (`--api-key=`, tokens, passwords, DB connection strings, etc.), regardless of root
- Tool returns are capped at ≤30 rows, with a limit of 4 tool-call rounds

## TL;DR

- Form: TUI (Python + Textual), not a web service
- Dependencies: psutil + textual + httpx
- Hardest pitfall: Linux per-process traffic monitoring (needs root, nethogs preferred)
- AI: OpenRouter + function calling, read-only tools, kill always human-confirmed
- Platforms: Linux first-class, macOS second-class, Windows not committed
