**English** | [繁體中文](PLAN.zh-TW.md)

# asktop — htop-like All-in-One System Monitoring Tool Planning Document

> Status: Phase 1 (MVP), Phase 2 (per-process traffic), Phase 3 (AI queries) implemented
> Date: 2026-07-21 (Section 10 is a later addendum of real-world measurements)
> Audience: Lewis's personal development tool (not a commercial SaaS, no multi-tenancy, no account system)
> Produced by: Fable5 model

---

## 1. Product Positioning and Core Value Proposition

**In one sentence**: An htop that "can see the network and can ask the AI"—integrating process monitoring, per-process network traffic, and port occupancy into a single interface, and letting you ask "what's happening with the system right now" directly in natural language.

### Differentiation from Existing Tools

| Tool | Process monitoring | Global traffic | Per-process traffic | Port occupancy view | Management ops (kill, etc.) | AI queries |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| htop / btop / bottom | ✅ strong | partial (btop has NIC graph) | ❌ | ❌ | ✅ | ❌ |
| glances | ✅ | ✅ | ❌ (not in core version) | partial | weak | ❌ |
| nethogs | ❌ | ❌ | ✅ (Linux) | ❌ | ❌ | ❌ |
| iftop / bandwhich | ❌ | ✅ | bandwhich has it (per-process/connection) | ❌ | ❌ | ❌ |
| `ss` / `lsof -i` | ❌ | ❌ | ❌ | ✅ (but a one-shot command, not a live view) | ❌ | ❌ |
| **This tool** | ✅ | ✅ | ✅ (Linux first) | ✅ (live, sortable and filterable) | ✅ | ✅ |

Core insight: today, to answer "why is the network slow / who's occupying 8080" you have to switch between three tools—htop, nethogs, `ss -tunlp`—and do the join in your head. **The value of this tool is to do that join for you, and hand off the last mile (interpreting the data) to the AI.**

The differentiation is not "monitoring done prettier than btop"—btop is already hard to beat visually—but rather:
1. **Integrated Process × network view** (see CPU, memory, traffic, and which ports are open all in the same row)
2. **AI investigation interface** (which no existing tool has)

---

## 2. Technical Architecture Recommendation

### 2.1 TUI vs Web Dashboard Trade-off Analysis

| Aspect | TUI | Web Dashboard |
|------|-----|---------------|
| The "htop-like" usage scenario (SSH into a VPS and run it directly) | ✅ naturally fits | ❌ needs port forwarding or an nginx front |
| Security | ✅ no network exposure surface | ❌ a web service that can kill processes exposed to the public internet is a risk |
| Deployment complexity | ✅ single command, no systemd/nginx/port | ❌ needs port registry, nginx conf, systemd |
| Multi-machine use | ✅ SSH into each and run, naturally isolated | each machine needs its own service instance |
| Chart richness | medium | ✅ strong |
| AI conversation UX | workable | ✅ slightly better |
| Fit with Lewis's Vue 3 familiarity | ❌ not used | ✅ |

**Recommendation: TUI, Python + Textual.**

Reason: the primary moment of use is "SSH into a VPS to troubleshoot"; opening a browser to connect to a dashboard is extra friction; killing a process from a TUI requires no authentication or exposure surface at all; deployment = `uv tool install` or just run it, occupies no port registry, no nginx to write, no systemd to enable.

The web version is downgraded to a future option (Phase 4): a read-only view layer, or `textual serve` to project the TUI directly into a browser.

### 2.2 Technology Choices

| Layer | Choice | Reason |
|----|------|------|
| Language | Python ≥ 3.12, managed with `uv` | matches Lewis's conventions |
| TUI framework | **Textual** | DataTable, reactive updates, Markdown widget, native async support |
| System data | **psutil** | cross-platform de facto standard |
| Per-process traffic | Linux: wrap **nethogs** (trace mode) or eBPF (python-bcc); macOS: parse **nettop** | see 2.3 and Section 7 |
| LLM calls | **httpx** directly to **OpenRouter** | matches Lewis's existing conventions, avoids heavy dependencies like langchain |
| Config | `.env` + `os.getenv()` | matches conventions |
| File structure | `asktop.py` (UI) / `collectors.py` / `config.py` / `wizard.py` | originally planned as a single file to start; during Phase 1 implementation it was split into four modules directly: `collectors` is the UI/collection separation required by risk #7 (does not import textual), `wizard` is a one-time flow unrelated to the main screen, and `config` contains sudo home-directory resolution that needs independent testing |

Total dependency target: **three—psutil + textual + httpx**. No FastAPI, no database (in-memory ring buffer).

### 2.3 How System Data Is Obtained on Each Platform

| Data | Linux | macOS | Windows |
|------|-------|-------|---------|
| Process list / CPU / mem | psutil | psutil | psutil |
| Global NIC traffic | psutil `net_io_counters()` delta | same as left | same as left |
| Connections / port occupancy | psutil `net_connections()`; without root you still get connections and the full LISTEN list, but only 36% have a pid (see Section 10) | same as above but without root it's a direct AccessDenied, all-or-nothing | needs real-world verification |
| **Per-process traffic** | No ready-made psutil API. Three paths: (a) wrap nethogs (least effort, needs root); (b) python-bcc/eBPF (the proper way but environment-sensitive); (c) roll your own pcap sniff + socket inode→pid mapping | `nettop -x -P -l 1` has native per-process bytes (output stability needs real-world verification) | ETW is the canonical approach; the Python ecosystem has no good path, **recommend explicitly marking it as unsupported** |

**Linux per-process traffic recommendation**: go with (a) wrapping nethogs—Section 10.2 has already verified that parsing is feasible, no need to switch to eBPF. All three paths need root. **Note that nethogs trace mode outputs cumulative KB rather than a rate, so you must diff it yourself.**

**Platform strategy**: **Linux is first-class (the VPS main battlefield), macOS is second-class (degradable), Windows is explicitly not committed**—pin the scope down from the start to avoid the project ballooning out of control.

---

## 3. Core Functional Module Breakdown

### 3.1 Process Monitoring Module
- **MVP**: table (PID/name/user/CPU%/MEM%/status), sort by any column, live filtering, kill (SIGTERM + secondary confirmation)
- **Advanced**: other signals, process tree, single-process detail page, CPU/mem sparkline history, nice adjustment

### 3.2 Network Traffic Monitoring Module
- **MVP**: global real-time up/down rate (per-NIC) + sparkline
- **Advanced (Phase 2 core)**: per-process up/down rate merged into the process table (the soul of the integrated view), per-connection traffic, sort by traffic

### 3.3 Port Occupancy Integrated View
- **MVP**: dedicated tab, listening ports table (port/protocol/address/PID/process name) = a resident `ss -tunlp`; click to jump to the corresponding process
- **Advanced**: full connections view, connection-status statistics; **cross-reference with Lewis's `/srv/projects/port-registry.json`**—annotate next to a port "this is agent-arena", extremely low implementation cost, a killer little feature

### 3.4 AI Query Interface
- **MVP**: conversation tab, function calling to query live state → streaming reply (Markdown), defaults to zh-TW
- **Advanced**: multi-turn follow-ups, referencing the historical ring buffer, AI-suggested operations (kill is always pressed by a human), quick questions

---

## 4. Concrete Design of the AI Query Feature

### 4.1 Core Decision: Function calling, do not stuff the entire snapshot at once
The problem with dumping a full system snapshot at once: a VPS easily has 200+ processes and hundreds of connections, most unrelated to the problem; it's already stale the moment it's sent, and can't fetch new data for follow-ups.

**Architecture: a small summary as the base + tools digging deeper on demand**
1. The system prompt attaches a "compressed summary" (hostname/uptime/load/CPU-mem overview/top5 CPU/top5 mem/current rates/listening port count), targeting a few hundred tokens
2. Read-only tools: `get_top_processes` / `get_process_detail` / `get_connections` / `get_listening_ports` / `get_net_rates` / `search_process`
3. Tool returns are capped (at most 30 rows, cmdline truncated)
4. Limit tool-call rounds (suggested cap of 4 rounds)

### 4.2 Prompt Design Points
- Role setup: a system-diagnosis assistant that answers only based on data queried via tools, and says it doesn't know when it doesn't
- Note the snapshot timestamp and the host identity (Lewis has multiple machines)
- **The AI has no write/kill tool**—it only investigates and advises; destructive operations are always confirmed and executed by a human in the UI
- Answer language: Traditional Chinese

### 4.3 Privacy Note
cmdline often contains secrets (`--api-key=xxx`, DB connection strings). Mask before sending to the LLM (regex to mask key/token/password-style parameter values).

### 4.4 API, Cost, and Latency
- OpenRouter (OpenAI-compatible + tools), model comes from `.env` config
- Concrete token/cost numbers **need real-world verification**, not hardcoded in advance
- Latency countermeasures: streaming output, a status line while a tool call is in progress, fully async UI

---

## 5. Data Update Mechanism

Principle: **the monitoring tool must not itself become the load.**

| Data | Cost | Suggested interval |
|------|------|----------|
| NIC counters | very low | 1s |
| process CPU/mem | medium | 2s (adjustable) |
| `net_connections()` full table | measured far below expectations (see Section 10) | 2s; "only query when the current tab is visible" is deferred, pending re-measurement under high connection counts on a VPS |
| per-process traffic (nethogs) | resident stream | aggregated per second |

Other mechanisms: visibility-driven collection, in-memory ring buffer (last 5–10 minutes), a pause key, self-monitoring (displaying its own CPU%, switching to lazy mode if nethogs overhead is too high).

---

## 6. Phased Development Roadmap

**Phase 0 — Technical validation spike**: verify nethogs parsing feasibility, psutil root/no-root differences, Textual DataTable smoothness at 200+ rows, macOS nettop parsing (can be deferred). This phase's conclusions directly decide the Phase 2 direction.

**Phase 1 — MVP (implemented)**: process table (sort/filter/kill), global traffic sparkline, port occupancy tab (with port-registry annotation), **first-run setup wizard** (see Section 9; the theme part must be done in the MVP, and the provider/model/API key parts must at least be settable, with skipping not blocking the monitoring features), `uv run asktop.py` runnable. Delivery criterion: SSH into a VPS and use it to troubleshoot one real problem without needing to switch back to htop/ss.

**Phase 2 — Per-process traffic (implemented, see 10.4)**: wrap nethogs, **diff cumulative values into rates**, filter out diagnostic-noise rows, merge `pid=0` into an "unattributed" row, merge the traffic column into the table; degrade gracefully without root / without nethogs.

**Phase 3 — AI queries (implemented)**: OpenRouter client + streaming, summary generator + 6 read-only tools + cmdline masking, conversation tab, quick questions. Tool round cap of 4 (the 5th request withdraws the tools, forcing the model to answer with existing data); tool results live only within a single round and do not enter long-term history, to avoid follow-ups treating an old snapshot as the current state.

**Phase 4 — Polish and extension (not committed)**: promote macOS support, process detail page, `textual serve` or read-only web layer evaluation, `uv tool install` packaging.

---

## 7. Potential Risks and Technical Challenges (an honest list)

| # | Risk | Description | Countermeasure |
|---|------|------|------|
| 1 | **Per-process traffic is the hardest part of the whole project** | Linux has no ready-made unprivileged API; nethogs/eBPF/pcap all need root and each has its own dependencies | Spike in Phase 0 first; design it to be degradable |
| 2 | **Root privilege requirement** | Seeing all users' pid↔socket and capturing packets both need root | **Run with sudo by default (full functionality)**; no-root is a degraded mode and **behaves per-platform** (see 10.1): Linux can still list ports but marks the owner column as "unknown", macOS shows the entire tab as "needs root". Use absolute paths for the config file (under sudo, `$HOME` becomes `/root`; reading/writing config must resolve to the caller's home directory) |
| 3 | Cross-platform commitment spiraling out of control | Full functionality across three platforms would make collectors the biggest source of complexity | Pin down Linux first-class / macOS second-class / Windows not committed from the start |
| 4 | AI latency hurting the experience | Multi-round tool-calling round-trips start at several seconds | streaming + progress hints + round cap |
| 5 | Privacy angle of sending system data to the LLM | cmdline / connection remote addresses may contain secrets | cmdline masking; the AI feature can be turned off entirely |
| 6 | AI hallucinating numbers | The LLM may fabricate values it never queried | prompt strictly orders it to cite only tool results; important conclusions can be cross-checked against the raw table |
| 7 | Textual dependency risk | The framework is still actively evolving, with occasional breaking changes | lock the version; separate the UI and collectors layers |
| 8 | The monitoring tool's own overhead | `net_connections()` full table + pcap cost is unclear | tiered polling + visibility-driven + own CPU% display; concrete overhead needs real-world measurement |
| 9 | kill mis-operation | Selecting the wrong row at the instant the table refreshes and killing the wrong process | confirmation box shows PID+name+cmdline; bind to the PID rather than the row position during confirmation |

---

## 8. Project Naming Suggestions

1. **`asktop`** (primary pick)—"ask + top", easy to type, points out the differentiation
2. **`omnitop`** (alternate)—emphasizes the integration positioning, but doesn't point out the AI selling point

---

## 9. First-Run Setup Wizard

**Trigger timing**:
- On the first run of `asktop` when no config file is found → automatically enter the wizard, which cannot be skipped (at least the theme step must be completed before reaching the main screen)
- Afterwards, at any time, `asktop setup` or a key in the main screen (suggested `s`) can manually re-enter the wizard to modify any setting

**Config file location and format**: `~/.config/asktop/config.json` (follows the XDG convention; not `.env`, because asktop is a globally installed CLI tool and, unlike a typical project, has no fixed working directory). Set permissions `600` when the file is created (it contains the API key, following the convention for credential files of ordinary CLI tools).

**Four settings**:

| Step | Content | UI design | Notes |
|---|---|---|---|
| 1. Model Provider | Choose an LLM service provider | Textual `RadioSet`: **OpenRouter** (default/primary pick), custom OpenAI-compatible endpoint (requires additionally entering a base URL, leaving room for future expansion; the MVP can do only OpenRouter first, keeping the UI skeleton in place) | Aligns with the existing choice in Section 2 (OpenRouter), introduces no extra SDK |
| 2. Model | Enter/choose the model id to use | An `Input` text box + a few common suggested values as placeholder/shortcut fill-ins (e.g. `anthropic/claude-sonnet-4.5`, `openai/gpt-4o-mini`), no live fetching of the model list (to avoid the wizard stage requiring a key before you can proceed) | Plain text input, does not validate whether the model exists—left to be confirmed together during the step 3 validation |
| 3. API Key | Enter the provider key | `Input(password=True)` masked input; upon confirmation immediately fire a minimal-cost validation request (such as OpenRouter `/models` or a very short completion), the screen showing "Validating…" → "✓ available" or "✗ validation failed, please re-enter" | The key is never printed to the screen/log/debug output; if the environment variable `ASKTOP_API_KEY` is detected as set, this step shows "environment variable detected, will be preferred" and can be skipped directly |
| 4. Theme | Dark / Light | `RadioSet`: **Dark** (default), Light; applied as a live preview the moment it's selected (**Textual 8.x has removed `App.dark`, use `App.theme = "textual-dark" / "textual-light"` instead**), no need to wait until the wizard ends to see the effect | Aligns with Lewis's consistent "dark mode default" preference (see the global CLAUDE.md convention) |

**Flow details**:
- The wizard uses several Textual `Screen`s chained together (or a single Screen switching via `Steps`/index), each step allows previous/next, and the final step shows a summary (provider / model / theme, with the key shown only as a few masked digits) + "Save"
- **The AI-related settings (steps 1–3) can be skipped as a whole**, without blocking the monitoring features—asktop's process/traffic/port monitoring inherently doesn't need the LLM. After skipping, the main screen's "AI query" tab shows "API Key not yet configured, press `s` to run the setup wizard" rather than an error or the whole feature disappearing
- theme (step 4) **cannot be skipped**, because it's the very presentation the wizard itself uses and must land a default value (default dark; even if the user just presses Enter to use all defaults, it counts as complete)
- After setup completes, it writes back to `~/.config/asktop/config.json`, and subsequent launches read it directly without re-entering the wizard (unless manually running `asktop setup`)
- On validation failure it does not block—it allows the user to choose "skip for now, set up later", which likewise lands in the "AI feature not enabled" state

**Relation to existing sections**: this section fills the "where the key is set" gap that Section 4.4 "API, Cost, and Latency" originally left unclear, and also makes the delivery scope of Section 6 Phase 1 MVP more complete (which originally only reached the monitoring features and didn't cover "how a user sets up the AI feature the first time they open it").

---

## 10. Phase 0 Real-World Measurement Records

> Environment: macOS (Darwin 23.6.0) local machine + Linux VPS (lewsi.ddns.net, a small machine: 140 processes / 28 connections). Scripts are in `spike/`.

### 10.1 psutil root vs no-root (`spike/spike_psutil_root.py`)

| Metric | macOS ordinary user | macOS root | Linux ordinary user | Linux root |
|---|---|---|---|---|
| `net_connections(kind="inet")` | **AccessDenied, gets nothing at all** | 145 entries / 3ms | 28 entries / 5ms | 27 entries / 7ms |
| of which pid is resolvable | — | 145 (100%) | **10 (36%)** | 27 (100%) |
| LISTEN | — | 13 | **16** | 16 |
| `process_iter()` | 742 / 41ms | 725 / 29ms | 140 / 32ms | 139 / 29ms |
| cmdline unavailable | 156 | 0 | **0** | 0 |

**Conclusions**:

1. **Degraded behavior is per-platform and cannot be written as a single copy**:
   - **macOS without root = all-or-nothing**: the connection table is entirely AccessDenied, the port tab can only show "needs root".
   - **Linux without root = partially visible**: connections are obtainable, **the LISTEN count is even completely identical (16 = 16)**, only 36% have a pid. So in Linux degraded mode the port tab still has practical value: list the ports as usual, marking the PID/program-name fields as "unknown (needs root)".
2. **Under root the pid resolution rate is 100% on both platforms**, so the process × connection join needs no fallback; the originally planned "parse `ss -tunlp` as a backup" need not be implemented.
3. **`net_connections()` cost was overestimated by an order of magnitude** (3–7ms, not the originally estimated "high"). The Section 5 polling strategy has been relaxed accordingly. **But both machines are small samples (145 / 28 entries), the high-connection-count scenario is still unverified**, so "visibility-driven collection" remains deferred rather than rejected.
4. **Linux without root can also read all cmdlines** (`/proc` is world-readable by default, unless `hidepid` is mounted). Privacy masking (Section 4.3) is therefore independent of whether it's root and is always necessary—asktop will see all users' full command lines, including the keys and connection strings within them.

### 10.2 nethogs parsing (`spike/spike_nethogs.py`, Linux VPS, 15 seconds)

Raw results: 16 refreshes (≈1/s, matching `-d 1`), 29 rows parsed successfully, 21 failed.

1. **The values are cumulative KB, not a rate**—this is the most important finding of this section; the original plan implicitly assumed a rate could be obtained directly. Evidence: the `unknown TCP` row shows recv of `0.0119141` across multiple consecutive samples (identical to seven decimal places—a rate can't possibly be like that), while sshd's sent increases monotonically `0.335 → 0.731 → 0.782 → 0.903 → 1.00`.
   **Design impact**: Phase 2 must diff adjacent samples itself to get a rate, and handle counter resets (process ending, nethogs restarting) and the case of no prior value on the first sample. A negative diff is treated as a reset rather than negative traffic.
2. **The 21 failed rows are all diagnostic noise, not format exceptions**: `Adding local address: ...`, `Ethernet link detected`, `Unknown connection: <ip:port-ip:port>`. Filtering out the known prefixes suffices; the regex itself needs no change.
3. **There is unattributable traffic**: `pid=0` paired with the program name `unknown TCP`. The table needs an "unattributed" aggregate row and must not silently drop it, otherwise the per-process traffic sum won't match the global NIC traffic and the user will think the tool is lying.
4. **Conclusion: the nethogs-wrapping route is feasible**, Phase 2 does not need to switch to eBPF.

### 10.3 Textual DataTable (`spike/spike_datatable.py`)

On the VPS it looked fine by eye, but that machine has only 139 processes and didn't test the "200+ rows" scenario. Re-measured on macOS (747 rows) using headless (`App.run_test()`) to compare incremental updates and full-table rebuilds:

| Mode | psutil collection | table update | cursor |
|---|---|---|---|
| Incremental (`update_cell`, changing only the 25–33 cells that changed) | 20–27ms | **1ms** | sticks to the original PID |
| Full-table rebuild (`clear` + `add_row`) | 22–23ms | 6–8ms | sticks to the original PID |

**Conclusions**:

1. **Cursor stability depends on "using PID as the row key", independent of incremental vs rebuild.** Neither mode drifts, because both use `add_row(key=pid)` + `get_row_index(pid)` to locate. The correct answer for risk #9 is binding the row key to PID, not being forced to use incremental.
2. **Table update is not the bottleneck; psutil collection is** (20–27ms, 3–4x more expensive than rendering). Although incremental is 6–8x faster, the absolute difference is only ~5ms, imperceptible at a 2-second refresh. **If performance is optimized later, the direction is the collection side, not the rendering side.**
3. At the 747-row scale Textual has no performance concern, so Phase 1 is free to choose the implementation approach; the reason to choose incremental should be avoiding flicker and preserving UI state, not performance.

**Measurement-contamination caveat**: the "own CPU 37–73%" shown in the spike status line comes from a stress scenario in the headless test that calls `refresh_table` continuously without an interval, and **does not represent the actual load under 2-second polling**; the real number needs to be re-measured after interactive execution.

### 10.4 Phase 2 End-to-End Verification (`spike/test_phase2.py`, VPS + sudo)

Downloading 20MB in the background to generate traffic, nethogs correctly attributed it to the initiating process:

```
3s  pid86111:↑6.1 ↓3777.5KB/s   ← curl
    pid81874:↑0.1 ↓0.1KB/s      ← sshd
4s  after the download ends pid86111 returns to zero, its row still remains in the list
未歸屬流量: ↑0.0 ↓0.0 KB/s
ports: 17, all have a PID (no "owner unknown" under root)
```

**Conclusions**:

1. **Per-process attribution is correct**, the approach of diffing cumulative values into rates holds, and the Phase 2 main path is proven.
2. **After traffic stops the row does not disappear, and the rate returns to zero**—answering half of the question 10.4 originally listed (the real "process ends" scenario is still untested, curl hadn't exited at the time).
3. **A process appearing for the first time may have its rate overestimated**: when a new pid first enters the snapshot there's no prior value, so it takes "cumulative amount ÷ a single interval" as the rate. Because nethogs itself also accumulates from startup, in practice the error is limited, but the first-second number for a burst of traffic running high is known behavior.
4. **Sort verification once produced an invalid result**: sorting by ↑KB/s on the VPS, the first few rows were systemd/kthreadd, seeming broken—actually all values were 0.0 at the time, and stable sorting preserved insertion order. After switching to a deterministic test injecting fixed rates, the sort was confirmed correct (50→40→30→20). **Lesson: all-zero data cannot verify sorting.**

### 10.5 Still To Be Verified

- **`net_connections()` timing under high connection counts**: both measured machines are small samples (≤145 entries), the scenario of hundreds to thousands of connections has no data yet.
- **Extreme behavior of the nethogs counter**: whether the row disappears after a process truly ends, the reset on pid reuse, whether it overflows during long-running execution.
- ~~**macOS `nettop` parsing** (the second-class platform route in Section 2.3) hasn't been touched at all.~~ Implemented in Phase 4, see 10.7.

### 10.6 issue #5 —— Supplementary Verification of the tools.py Per-Process Traffic Path (VPS + sudo, `spike/test_phase5.py`)

On macOS `flow()` is always None, so the "feed the AI" path of `tools._flow_rows` / `_net_rates` / `_top_processes(sort_by="net")` had never actually executed. On the VPS, after generating a download of a known pid with throttled curl (50MB @ 3MB/s):

1. **Attribution is correct**: nethogs attributes the download back to curl's pid, and the tool's output `PID + program name` matches.
2. **Unattributed traffic (pid=0) is listed**, not silently dropped.
3. **After traffic stops the pid returns to zero** (the diff's handling of the counter stopping is correct).
4. `get_net_rates` / `get_top_processes(net)` take the nethogs branch, not the macOS degraded-copy path.

**Observation**: the rate nethogs diffs out (curl 113.5K/s) is clearly lower than the global NIC downlink (2.6M/s); this is the known sampling characteristic of first-sample/averaging (see 10.4 conclusion 3), not an attribution error.

**cloudflare speed endpoint caveat**: `__down?bytes=` beyond the limit (measured at 300MB) returns 403; use 50MB to generate traffic.

**AI end-to-end (manually confirmed 2026-07-22)**: on the VPS, actually asking the AI "who's eating the bandwidth", the AI correctly cited curl's per-process traffic. At this point issue #5 (tool-data layer automation) + the main scenario of issue #3 (AI citation, manual) both pass on both axes.

### 10.7 Promoting macOS Per-Process Traffic (Phase 4, `collectors.Nettop` + `spike/test_nettop.py`)

The original plan had macOS as a second-class platform with per-process traffic deferred (Section 2.3). Measurement showed macOS's built-in `nettop` is fully usable, so the `Nettop` class was implemented (symmetric to `Nethogs`), and `asktop` now selects via `flow_monitor()` per platform. Measured conclusions:

1. **nettop does not need root**—this is the biggest contrast with Linux. On macOS `net_connections()` (port/connection owner) is entirely AccessDenied without root (10.1), but **traffic** via nettop is obtainable by an ordinary account. So macOS without root can still have a per-process traffic column, only the port tab still needs root.
2. **The `-d` delta mode gives interval bytes directly**, without needing to diff cumulative values like nethogs or handle counter resets (once a process ends it no longer appears in the samples).
3. **`nettop -P -x -d -s 1 -J bytes_in,bytes_out -l 0`** is the chosen invocation: per-process aggregation, formatting off, keeping only the two bytes columns, continuous output. Samples are separated by a `time …` header line.
4. **The name column contains spaces and is truncated** ("Google Chrome H"), so `Nettop` returns only `pid→rate`, and the name is always resolved from psutil's process list—consistent with the nethogs path.
5. **`bytes_in`=downlink, `bytes_out`=uplink**, mapped to `(up, down)` to align with `Nethogs`.
6. `spike/test_nettop.py` (root-free) verifies: throttled curl is precisely attributed to its pid (↓ matching the 3M throttle), takes the traffic branch rather than the degraded copy, and eventually returns to zero on polling after stopping. Headless also confirms the macOS app creates the ↑/↓KB/s columns and hides the "not enabled" hint.

**Known trade-off**: pid 0 on macOS is kernel_task (real kernel traffic), which will be shown using the tools' "unattributed" row; the semantics are slightly off but the traffic is usually near 0, so it's not handled specially.

---

## TL;DR

- **Form**: TUI (Python + Textual), no web service—zero friction for the SSH scenario, zero security exposure surface
- **Dependencies**: three—psutil + textual + httpx; managed with `uv`; starts as a single file
- **The hardest pitfall**: Linux per-process traffic—**Phase 0 has verified that wrapping nethogs is feasible** (but the output is cumulative values, so you must diff it yourself). The root requirement can't be bypassed, **run with sudo by default**, and the no-root degraded behavior is per-platform (see Section 10)
- **AI**: OpenRouter + function calling (small summary + read-only tools + round cap + cmdline masking, kill always confirmed by a human)
- **Config**: a first-run wizard guides setting provider/model/API key/theme, stored in `~/.config/asktop/config.json` (600 permissions); AI settings can be skipped without blocking the monitoring features, theme cannot be skipped (default dark)
- **Scope discipline**: Linux first, Windows not committed, the web view layer deferred
