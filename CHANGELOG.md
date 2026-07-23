**English** | [繁體中文](CHANGELOG.zh-TW.md)

# Changelog

This file records all notable changes to asktop.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versioning follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-07-23

### Added

- **i18n / English locale**: added a lightweight dict-based i18n (`i18n.py`), English by default with Traditional Chinese available, no new dependencies; all UI strings now go through `i18n.t()`. Added `spike/test_i18n.py`.
- **Wizard language selection**: language is now the first wizard step (defaults to English), applied live and stored in config `lang`.
- **LLM provider presets**: provider selection is now `openrouter / openai / claude / gemini / custom`; picking one fills in the corresponding OpenAI-compatible `base_url` (`llm.py` core unchanged). Added `config.PROVIDERS`.
- **Bilingual documentation**: `README` / `PLAN` / `CHANGELOG` / `CLAUDE` are now English-primary, with the Chinese content preserved as `*.zh-TW.md` and cross-linked.

### Changed

- **The default UI language is now English** (previously Traditional Chinese); switch it in the setup wizard or via the config `lang` field. Existing config files auto-default to `en` (no migration needed). The AI reply language follows the UI language.

### Fixed

- **Ports tab: the selected row no longer jumps back to the top on refresh.** `tick_ports()` changed from a full-table rebuild to an incremental update, using a stable row key (`proto|addr|port|pid`) and restoring the cursor after refresh, matching the process table's discipline. Added `spike/test_ports.py` (headless, no root).

## [0.1.0] - 2026-07-22

### Added

- **macOS per-process traffic** (Phase 4): added `collectors.Nettop`, wrapping macOS's built-in `nettop`. Previously the traffic columns were not created at all on macOS and only a "Linux only" notice was shown; now macOS can also see each program's ↑/↓ rate in the process table, and it feeds the AI's `get_net_rates` / `get_top_processes(sort_by="net")`.

  Key differences: nettop **does not require root** (only connection/port ownership needs root), and its `-d` delta mode gives interval bytes directly, so no manual differencing is needed as with nethogs. `asktop` now uses `collectors.flow_monitor()` to pick nethogs / nettop per platform, with the same interface. Added `spike/test_nettop.py` (macOS, no root) to verify correct attribution and reset-to-zero after stopping. The tools' net description no longer hardcodes "Linux only".

- `spike/test_phase5.py` (needs Linux + root + nethogs): adds coverage for the per-process traffic path in `tools.py` (`_flow_rows` / `_net_rates` / `_top_processes(sort_by="net")`), which is never reached on macOS and was never touched by Phase 3's automated verification. It uses a throttled curl to generate a download from a known pid, confirming that nethogs attribution is correct, that the pid=0 unattributed row is not dropped, that traffic resets to zero after it stops, and that it takes the nethogs branch rather than the degraded notice. Corresponds to [#5](https://github.com/Lewsiafat/asktop/issues/5), verified on a VPS (PLAN.md 10.6).

## [0.0.2] - 2026-07-21

### Fixed

- **Re-running the setup wizard would silently wipe the configured model** ([#4](https://github.com/Lewsiafat/asktop/issues/4)). Entering the wizard with `s` from the main screen and pressing "Next" all the way to save would overwrite `model` with an empty string, dropping the AI tab back to the "not configured" guidance. The API key survived instead (step 3 treats an empty value as skip), so the symptom was "the key is still there but the AI suddenly stopped working" — not easy to trace back to the wizard.

  The cause was two defects stacked together: the input fields had only placeholders and did not backfill current values, and "Next" unconditionally overwrote the config with the field values. The four widgets `model` / `base_url` / `provider` / `theme` were changed to be preloaded from the existing config.

- `asktop setup` previously restarted from defaults, resetting even theme and port_registry_path; it now loads the existing config, consistent with pressing `s` on the main screen.

### Changed

- The API key field deliberately does not backfill in plaintext (the wizard is for changing settings, not for viewing the key); step 3 now shows "leave blank to keep the current one." "Skip AI setup" still explicitly clears model and key — that is the user's intent.

### Added

- `spike/test_wizard.py` (19 checks): covers backfilling current values, pressing Next all the way through without changing any setting, edits actually taking effect, replacing the key, skip still clearing everything, first run being unaffected by backfilling, and `asktop setup` matching the behavior of pressing `s`. Total verification scripts increased to 186 checks.

## [0.0.1] - 2026-07-21

The first tagged version, covering the full Phase 1–3 scope promised by PLAN.md.

### Added

**Process monitoring (Phase 1)**

- Process table: PID / user / CPU% / MEM% / name, sortable by any column, live filtering
- kill (SIGTERM + confirmation). The confirmation dialog is bound to the PID, not the row position, and shows PID + name + cmdline
- Global network traffic live rate and sparkline (about 2 minutes retained)
- Port usage tab: listening-ports table, can cross-reference `port-registry.json` to annotate the owning project
- First-run setup wizard (five steps: provider / model / API key / theme / confirm). The AI-related steps can be skipped as a group without blocking monitoring
- Pause key, self CPU% display (a monitoring tool must not become the load itself)

**Per-process traffic (Phase 2)**

- Wraps `nethogs -t`, merging up/down rates into the process table
- Differences cumulative KB into rates itself; a negative difference is treated as a counter reset
- `pid=0` traffic is shown in an "unattributed" row rather than silently dropped — otherwise the per-process sum will not match the global figure
- Enabled only on Linux + root + nethogs; otherwise the traffic columns are not created at all (filling in 0 would make "no data" look like "no traffic")

**AI querying (Phase 3)**

- AI chat tab: OpenRouter (OpenAI-compatible) streaming, Markdown rendered token by token, Traditional Chinese
- A compressed system summary injected into the system prompt: hostname / uptime / load / CPU-mem overview / top 5 by CPU and memory / current rates / listening-port count
- Function-calling agent loop with six **read-only** tools: `get_top_processes`, `get_process_detail`, `get_connections`, `get_listening_ports`, `get_net_rates`, `search_process`
- cmdline secret masking (`mask.py`): `--api-key=`, `KEY=VALUE`, `--token VALUE`, `Bearer`, `scheme://user:pass@`, and bare tokens like `sk-` / `ghp_` / `AKIA`
- A status line is shown in the chat area while a tool call is in progress; four one-tap quick questions
- When the API key / model is not configured, guidance is shown instead of an error

**Verification scripts**

- Added `test_mask` / `test_llm` / `test_summary` / `test_tools` / `test_ai_ui` under `spike/`, 167 checks total, without installing pytest (to keep the three-dependency goal)
- LLM-related tests use `httpx.MockTransport`, without hitting the real network
- Phase 0 technical verification scripts: `spike_psutil_root` / `spike_nethogs` / `spike_datatable` / `test_phase2`

### Security

- The AI has no write or kill tool. Destructive operations are always confirmed and executed by a human in the UI
- cmdline is always masked before being sent to the LLM, regardless of root (on Linux `/proc` is world-readable by default, so even non-root can read every user's full command line)
- Tool returns are capped at ≤30 rows, cmdline is truncated; tool-call rounds are limited to 4
- The API key never enters the screen / log / debug output; error messages take only the exception class and message, not `repr` (httpx's repr includes the request object, which carries the authorization header)
- The config file `~/.config/asktop/config.json` is created with permission 600; under sudo it resolves back to the caller's home directory and returns file ownership

### Known limitations

- Per-process traffic is Linux + root + nethogs only; the macOS `nettop` route is not yet implemented
- Windows is explicitly unsupported
- `asktop.py setup` restarts from defaults and does not load the existing config file (pressing `s` on the main screen correctly preloads current values)
- No measured data yet for `net_connections()` cost under high connection counts (hundreds to thousands)
