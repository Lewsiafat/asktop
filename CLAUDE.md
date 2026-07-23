**English** | [繁體中文](CLAUDE.zh-TW.md)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**v0.1.0 — Phase 1 MVP, Phase 2 (per-process traffic), and Phase 3 (AI querying) are implemented; Phase 4 has started (macOS per-process traffic made official via `nettop`).** What remains are the other non-committed Phase 4 items.

For the change log see `CHANGELOG.md` (Keep a Changelog format); use `/release` for the release process.

Per-process traffic is enabled on Linux (root + nethogs) and macOS (`nettop`, no root required); `collectors.flow_monitor()` selects `Nethogs` / `Nettop` per platform. Otherwise the traffic columns are not created at all (filling in 0 would make "no data" look like "no traffic").

`PLAN.md` is the single authoritative source of spec; §10 records the Phase 0 measured data. If any implementation decision conflicts with PLAN.md, confirm with the user first, and update PLAN.md in sync.

## Commands

```bash
uv sync                              # install dependencies
sudo .venv/bin/python asktop.py      # run (sudo by default; without root it degrades)
sudo .venv/bin/python asktop.py setup  # re-run the setup wizard
uv run spike/spike_psutil_root.py    # Phase 0 verification script; see the docstring in each spike/ file
```

**Do not use `sudo uv run`** — it leaves root-owned files in `.venv`/cache, and later a normal-account `uv sync` will hit permission errors.

**There is no test framework** (pytest is not installed, to keep the three-dependency goal). Verification scripts live in `spike/test_*.py`, using plain asserts + `✓/✗` output, exit 1 on failure:

```bash
for t in mask llm summary tools ai_ui wizard; do .venv/bin/python spike/test_$t.py; done
```

Among these, `test_mask` / `test_llm` / `test_tools` need neither root nor the network (httpx `MockTransport`). Platform-specific traffic verification is run separately: `test_phase2` / `test_phase5` need Linux + sudo, and `test_nettop` needs macOS (no root, but it hits the network to generate traffic).

The UI relies on Textual's headless mode (`App.run_test()`), for example:

```python
async with app.run_test() as pilot:
    await pilot.pause()
    ...
```

Note that under headless mode, rapidly clicking the same widget twice will have the second click swallowed (Textual event coalescing); when testing multi-step flows, call the handler method directly instead. Also, the self CPU% measured by calling a refresh function repeatedly is not meaningful. **Widgets on a non-active tab cannot be clicked** (`pilot.click` fails silently), so before testing the AI tab set `query_one(TabbedContent).active = "tab-ai"` first.

## Module structure

- `collectors.py` — system data collection + the compressed summary used by the AI, **does not import textual** (the layering required by risk #7)
- `mask.py` — cmdline secret masking, pure functions, zero dependencies
- `tools.py` — the AI's 6 read-only tools and schemas, **does not import textual**
- `llm.py` — OpenRouter streaming client and agent loop, **does not import textual**
- `config.py` — config read/write, including sudo home-directory resolution
- `wizard.py` — first-run setup wizard
- `asktop.py` — UI and main loop

PLAN.md originally said "start as a single file"; during Phase 1 implementation this was changed to the structure above (§2.2 has been synced).

## Product positioning

asktop = "an htop that can see the network and can ask an AI." The differentiation is not about making monitoring prettier than btop, but about two things neither existing tool does:

1. **An integrated Process × network view** — see CPU, memory, per-process traffic, and which ports are open on the same row (replacing manual joins across htop / nethogs / `ss -tunlp`)
2. **An AI investigation interface** — ask "what's going on with the system right now?" in natural language

## Settled architecture decisions

These are decisions already weighed in PLAN.md; follow them directly during implementation, do not reinvent them:

- **TUI, not a web service**. Reason: SSHing into a VPS to troubleshoot is the primary scenario; a service that can kill processes exposed to the public internet is a risk. A web version is a non-committed Phase 4 option (`textual serve` or a read-only view layer).
- **Total dependency target of three: psutil + textual + httpx**. Do not bring in langchain, FastAPI, or a database (historical data uses an in-memory ring buffer). Python ≥ 3.12, managed with `uv`.
- **Separate the UI layer from the collectors layer** — Textual carries breaking-change risk, and data collection should not be tied to it.
- **Platform scope is nailed down**: Linux first-class (the main VPS battlefield), macOS second-class (can degrade), Windows explicitly not committed. Uncontrolled cross-platform commitments are this project's biggest scope-creep risk.
- **The LLM goes through OpenRouter** (OpenAI-compatible + tools), called directly with httpx, with the model id decided by the config file.

## Development roadmap (the phase order is intentional)

- **Phase 0 — spike**: verify nethogs output parsing, psutil root/no-root differences, and Textual DataTable smoothness at 200+ rows. **This phase's conclusions directly decide the direction of Phase 2 — do not skip it.**
- **Phase 1 — MVP**: process table (sort/filter/kill), global-traffic sparkline, port-usage tab, first-run setup wizard. Delivery criterion: being able to use it to troubleshoot one real problem on a VPS without switching back to htop/ss.
- **Phase 2 — per-process traffic (done)**: nethogs wrapper, traffic columns merged into the table. Verification must run `spike/test_phase2.py` on Linux + sudo.
- **Phase 3 — AI querying**: OpenRouter client + streaming, summary + 6 read-only tools + cmdline masking.
- **Phase 4 — non-committed**: making macOS official, `uv tool install` packaging, evaluating a web layer.

## Hard constraints during implementation

These few are security/privacy related; violating them causes real trouble:

- **The AI has no write or kill tool.** The LLM can only investigate and advise; destructive operations are always confirmed and executed by a human in the UI.
- **cmdline must be masked before being sent to the LLM** (patterns like `--api-key=`, tokens, passwords, DB connection strings). The AI feature can be turned off entirely.
- **The AI may only cite data returned by tools.** The prompt explicitly says to admit not knowing rather than hallucinate numbers. Tool returns are capped (≤30 rows), and the recommended tool-call round limit is 4.
- **DataTable always uses the PID as the row key** (`add_row(key=pid)`). This is the root fix for a non-drifting cursor and not killing the wrong process (measured in PLAN.md 10.3), independent of whether updates are incremental or rebuilt. The confirmation dialog must show PID + name + cmdline.
- **The API key never enters the screen / log / debug output.** The config file `~/.config/asktop/config.json` is created with `600`.
- **The monitoring tool must not become the load itself.** Layered polling (NIC counters 1s, process 2s, full `net_connections()` scan 3–5s and only when the current tab is visible), visibility-driven collection, self CPU% shown in the UI.
- **sudo by default.** The non-root degradation behavior **differs per platform** (measured in PLAN.md 10.1): Linux can still list ports but only 36% have a pid, with the owner column marked "unknown"; macOS is a full AccessDenied and can only show "root required." Do not write them as the same copy. Likewise, when the AI is not configured, the chat tab shows guidance rather than an error.
- **nethogs output is cumulative KB, not a rate** — it must be differenced yourself; a negative difference is treated as a counter reset. `pid=0` traffic goes into the "unattributed" row and must not be silently dropped, otherwise the per-process sum will not match the global NIC traffic.
- **cmdline masking is independent of root**: Linux `/proc` is world-readable by default, so even non-root can read every user's cmdline.
- **Under sudo, `$HOME` becomes `/root`** — reading/writing `~/.config/asktop/config.json` must resolve back to the caller's home directory (`SUDO_USER`), otherwise the config is saved in the wrong place.

## Language conventions

The default language for user communication, code comments, and AI replies is **Traditional Chinese**. The UI defaults to a dark theme.

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues (using the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` at the repo root + `docs/adr/`. See `docs/agents/domain.md`.
