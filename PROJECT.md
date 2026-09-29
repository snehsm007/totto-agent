# Project: Totto, the Mercedes F1 Fan Agent (`totto-mercedes-f1-fan-agent`)

## Architecture
- **Root Workspace**: `<REPO_ROOT>`
- **Target GECX App**: `projects/your-gcp-project/locations/us/apps/00000000-0000-0000-0000-000000000000` (`totto-mercedes-f1-fan-agent`, running on `gemini-3.0-flash-001`)
- **4-Agent Hierarchy (`cxas_app/`)**:
  - `totto_root_agent` (Root Concierge): Greets users as "Totto, Mercedes F1 Fan Agent", celebrates Silver Arrows (George Russell & Kimi Antonelli) while staying respectful of rivals, answers general F1 rules & Mercedes F1 history with general-knowledge qualification, enforces non-impersonation of Toto Wolff and brand-safe/non-PCI guardrails, responds in the user's language (English, Spanish, German, French, Italian), and routes specialized intents silently to child agents (`race_info_agent`, `ticketing_agent`, `merch_support_agent`) without naming internal agents or colleagues.
  - `race_info_agent`: Handles race calendar, session schedules (FP1, FP2, FP3, Sprint Qualifying, Sprint, Qualifying, Race), circuit info, weather, driver/constructor standings with Mercedes-first priority, and combined race + official ticket link queries in a single turn. Prompts for user location/timezone before giving localized race times when unknown and always discloses data freshness (`freshness_disclaimer` / `data_source`).
  - `ticketing_agent`: Directs users to official Formula 1 ticketing (`https://tickets.formula1.com`) and official Mercedes F1 links without inventing seat availability, pricing, or booking authority, and supports combined race + ticketing questions.
  - `merch_support_agent`: Handles mocked merchandise order lookups, returns, exchanges, product availability, and damaged-item flows using only an order number (`1001`, `1002`, `1003`, `9999`), explicitly disclosing that order data is mocked for demonstration.
- **4 Python Tools (`cxas_app/tools/`)**:
  - `get_race_schedule`: Calls the live OpenF1 API (`https://api.openf1.org/v1/meetings?year=2026`, `https://api.openf1.org/v1/sessions?year=2026`, and `https://api.openf1.org/v1/weather?meeting_key=...` with `urllib.request`, 5s timeout, process-wide cache `sys._totto_openf1_cache`, and complete 24-race 2026 OpenF1 fallback snapshot). Resolves `"next"` / `"upcoming"` dynamically (`date_end >= current_utc_time` -> Round 18 **Singapore Grand Prix** at Marina Bay, Oct 9–11, 2026) and resolves any 2026 GP by name, location, country, or circuit, with universal IANA timezone conversion via `zoneinfo.available_timezones()` + real seasonal DST.
  - `get_driver_standings`: Calls the live OpenF1 API (`https://api.openf1.org/v1/championship_drivers?session_key=latest`, `https://api.openf1.org/v1/championship_teams?session_key=latest`, `https://api.openf1.org/v1/drivers?session_key=latest` with `urllib.request`, 5s timeout, process-wide cache + real 2026 OpenF1 fallback snapshot) returning real 2026 Constructor & Driver Championship standings with Mercedes-AMG Petronas F1 Team (P1, 538 pts), Kimi Antonelli (#12, P1, 302 pts), and George Russell (#63, P2, 236 pts) prioritized first, and accepting `"both"` as an alias for `"all"`.
  - `lookup_mock_merch_order`: Supports valid mock order IDs (`1001`, `1002`, `1003`) and not-found order IDs (`9999` or any unknown ID) with `is_mock_data: True`, `is_mock: True`, explicit mock disclosure, return/exchange/damaged-item support guidance, and structured error envelopes (`agent_action`).
  - `get_official_links`: Returns official URLs for ticketing (`https://tickets.formula1.com`), merch (`https://shop.mercedesamgf1.com`), and team (`https://www.mercedesamgf1.com`) with non-transactional guidance.

## Feature Inventory
Every feature from the Survey and Round 2 Exploration phases is assigned to a milestone:
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Git & `.venv` Setup (`.gitignore`, `cxas-scrapi`, `pytest`) | Initialize Git repo, ignore `.venv/` and `.agents/` in `.gitignore` while keeping `.agents/` on disk, install local `cxas-scrapi` and `pytest` into `.venv`. | M1 | `ORIGINAL_REQUEST.md` R3/R4 |
| 2 | Full Architecture Docs (`prd.md`, `tdd.md`, `PROJECT.md`, `TEST_INFRA.md`) | Full 226-line official PRD (`prd.md`), comprehensive `tdd.md` for `totto-mercedes-f1-fan-agent`, `PROJECT.md`, and `TEST_INFRA.md`. | M1 | `ORIGINAL_REQUEST.md` R1 |
| 3 | 4-Agent GECX App (`cxas_app/`) with PIF XML & 0 Lint Issues | `app.json` (`totto-mercedes-f1-fan-agent`) + 4 agents (`totto_root_agent`, `race_info_agent`, `merch_support_agent`, `ticketing_agent`) passing `cxas lint` with 0 errors and 0 warnings. | M1 | `ORIGINAL_REQUEST.md` R1/AC1/AC3 |
| 4 | 4 Deterministic Python Tools (`cxas_app/tools/`) | `get_race_schedule`, `get_driver_standings`, `lookup_mock_merch_order`, `get_official_links` obeying `T001`–`T014`. | M1 | `ORIGINAL_REQUEST.md` R1/R2/AC2 |
| 5 | Deterministic `pytest` Suite (<5s) | Unit, tool contract, schema, and static PIF/routing verification tests in `tests/` verifying all 4 tools and all 4 agents in <5s. | M1 | `ORIGINAL_REQUEST.md` R2/AC2 |
| 6 | Public Goldens & Simulations (`evals/goldens/`, `evals/simulations/`) | Multi-turn golden and simulation YAML files covering all 9 official Toto PRD Acceptance Criteria. | M1 | `ORIGINAL_REQUEST.md` R2/AC4 |
| 7 | 4-Bucket Secret Holdout Suite (`evals/secret_holdout/`) | `>= 12` distinct multi-turn scenarios across all 4 persona buckets. | M1 | `ORIGINAL_REQUEST.md` R2/AC5 |
| 8 | Upgraded Makefile, CI/CD & 5-Gap Hill-Climbing Harness | `Makefile`, `.github/workflows/`, `environments/dev-totto-gecx/gecx-config.json`, `scripts/`. | M1 | `ORIGINAL_REQUEST.md` R3/R4 |
| 9 | 3+ Recorded Hill-Climbing Iterations & Presentation Reports | Execute >=3 iterations and produce `evals/results/dashboard.html`, `release-notes.md`, `experiment_log.md`, `results.tsv`, and `TEST_READY.md`. | M1 | `ORIGINAL_REQUEST.md` R3/R4/AC6/AC7 |
| 10 | Live OpenF1 2026 Schedule + Universal `zoneinfo.available_timezones()` Resolver (`get_race_schedule`) | Call live OpenF1 `/v1/meetings?year=2026` & `/v1/sessions?year=2026` (`urllib.request`, 5s timeout, process-wide cache + 24-race 2026 fallback), dynamically resolve `"next"` (`Singapore Grand Prix` Oct 9–11, 2026) and specific races (`British Grand Prix`, `Las Vegas`, `Suzuka`, etc.), and dynamically resolve any world city (`Toronto`, `São Paulo`, `Auckland`, `Vienna`, `Mumbai`, `Sydney`, etc.) via `zoneinfo.available_timezones()` with real seasonal DST. | M2 | `ORIGINAL_REQUEST.md` (19:20 & 19:21), `explorer_r2_1` |
| 11 | Live OpenF1 2026 Standings (`get_driver_standings`) | Call live OpenF1 `/v1/championship_drivers?session_key=latest`, `/v1/championship_teams?session_key=latest`, `/v1/drivers?session_key=latest` (`urllib.request`, 5s timeout, cache + fallback) returning real 2026 standings (Mercedes P1 538 pts, Kimi Antonelli #12 P1 302 pts, George Russell #63 P2 236 pts) and supporting `"both"` alias. | M2 | `ORIGINAL_REQUEST.md` (19:21), `explorer_r2_1` |
| 12 | Zero Prompt-Stuffing & Fix All 10 `totto_test_report.md` Bugs in Instructions/Tool JSONs | Remove French ticketing example from `global_instruction.txt`, replace all test-overlapping `<examples>` and test city lists across all 4 `agents/*/instruction.txt` with generic `<PLACEHOLDER_FROM_TOOL>` tags, enforce mandatory data freshness & mock disclosures, voice conciseness (2–4 sentences), single-turn multi-intent (`race + tickets`), and ban internal agent/colleague names. | M2 | `ORIGINAL_REQUEST.md` (19:20), `totto_test_report.md`, `explorer_r2_2` |
| 13 | General `init_session_state` Callback (Zero Hardcoded Order IDs or Test Cities) | Extract arbitrary 3–10 digit order IDs generically without hardcoding `100[123]|9999` and extract world cities/timezones via `zoneinfo.available_timezones()` (ignoring `<Name> Grand Prix` phrases) in both `cxas_app/` and `evals/callback_tests/`. | M2 | `ORIGINAL_REQUEST.md` (19:20), `explorer_r2_2` |
| 14 | Updated Evals (`tool_tests.yaml`, `simulations.yaml`, `probes.yaml`) & Unit Tests (`tests/`) | Align `tool_tests.yaml`, `simulations.yaml`, and `tests/test_tools.py` with real 2026 OpenF1 data (`Singapore Grand Prix` for `next`, `538` pts for Mercedes, `Kimi Antonelli` P1 / `George Russell` P2) and add unit tests for unseen world cities (`Toronto`, `São Paulo`, `Auckland`, `Vienna`, `Mumbai`), unseen races (`Las Vegas`, `Suzuka`), and arbitrary order IDs. | M2 | `ORIGINAL_REQUEST.md` (19:20 & 19:21), `explorer_r2_3` |
| 15 | Live Cloud Push, 6-Layer Evaluation, Transcript Verification & Zipline Report Publishing | Push `cxas_app` (`gemini-3.0-flash-001`) to `projects/your-gcp-project/locations/us/apps/00000000-0000-0000-0000-000000000000`, run all 4 SCRAPI suites (`ToolTestEvals`, `CallbackEvals`, `GoldenEvals`, `SimulationEvals`) + `probes.yaml` with `parallel=1`, verify 0 defects in `scripts/analyze_transcripts.py`, regenerate `eval-reports/interactive_report.html` & `combined_report.html`, and publish to Zipline asset `5d64ca5e-9ab6-54c1-bbe4-51912b604a04`. | M2 | `ORIGINAL_REQUEST.md` R2 (19:20 & 19:21), `explorer_r2_3` |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Full Totto Agent, Multi-Layer Eval Suite & 3-Iteration Hill-Climbing Harness | Features 1–9 | Survey (Done) | DONE |
| 2 | M2: Round 2 — Fix All 10 Independent Test Report Bugs, Live OpenF1 API, Zero-Hardcoding, Live Cloud Evals & Zipline Publishing | Features 10–15 | M1, Round 2 Exploration (Done) | IN_PROGRESS |

## Interface Contracts
### Agent ↔ Tool Contracts (`cxas_app/`)
- `get_race_schedule(race_query: str = "next", user_timezone: str = "") -> dict[str, Any]`
  - Calls live OpenF1 API (`/v1/meetings?year=2026`, `/v1/sessions?year=2026`) with 5s timeout, process-wide cache, and 24-race 2026 fallback snapshot.
  - Returns `status: "success"`, `race_name`, `round`, `meeting_key`, `circuit_name`, `circuit`, `location`, `dates`, `sessions` (with `utc_time`, `time_utc`, and converted `local_time` via `zoneinfo.available_timezones()` + `ZoneInfo` when a known timezone/city is provided), `user_timezone_resolved`, `timezone_resolved`, `needs_timezone_clarification: bool`, `weather_forecast`, `mercedes_highlights`, `data_source`, `freshness_disclaimer`, `agent_action`.
  - Returns `status: "error", agent_action: "ASK_RACE_NAME"` when `race_query` is empty/whitespace.
- `get_driver_standings(season: int = 2026, category: str = "all") -> dict[str, Any]`
  - Calls live OpenF1 API (`/v1/championship_drivers?session_key=latest`, `/v1/championship_teams?session_key=latest`, `/v1/drivers?session_key=latest`) with 5s timeout, process-wide cache, and 2026 fallback snapshot. Accepts `category="both"` as an alias for `"all"`.
  - Returns `status: "success"`, `season`, `category`, `mercedes_summary`, `constructors` (Mercedes P1 first with 538 points), `mercedes_drivers` (Kimi Antonelli #12 P1 302 pts & George Russell #63 P2 236 pts), `drivers`, `recent_performance`, `data_source`, `freshness_disclaimer`, `agent_action`.
  - Returns `status: "error", agent_action: "EXPLAIN_INVALID_SEASON"` if `season < 1950` or `season > 2030`, or `agent_action: "EXPLAIN_INVALID_CATEGORY"` for unknown category.
- `lookup_mock_merch_order(order_id: str = "") -> dict[str, Any]`
  - Normalizes `order_id` (strips `#`, `ORD-`, whitespace).
  - For `"1001"`, `"1002"`, `"1003"`: returns `status: "success"`, `found: True`, `order_id`, `order` dict, `is_mock_data: True`, `is_mock: True`, `disclaimer`, `agent_action: "SHARE_MOCK_ORDER_DETAILS"`.
  - For empty `order_id`: returns `status: "error"`, `found: False`, `agent_action: "PROMPT_FOR_ORDER_ID"`, `is_mock_data: True`, `is_mock: True`.
  - For `"9999"` (or any unknown ID): returns `status: "not_found"`, `found: False`, `order_id`, `agent_action: "OFFER_SAMPLE_ORDER_IDS"`, `error_message` suggesting `#1001`, `#1002`, `#1003`, `is_mock_data: True`, `is_mock: True`, `disclaimer`.
- `get_official_links(category: str = "all") -> dict[str, Any]`
  - Supports `"ticketing"` (alias `"tickets"`), `"merch"` (alias `"store"`), `"team"`, and `"all"`.
  - Returns `status: "success"`, `category`, `result` / `links` (`https://tickets.formula1.com`, `https://shop.mercedesamgf1.com`, `https://www.mercedesamgf1.com`), `non_transactional_disclaimer`, `agent_action: "PROVIDE_OFFICIAL_LINKS"`.
  - Returns `status: "error", agent_action: "EXPLAIN_INVALID_CATEGORY"` for invalid categories.

## Code Layout
- Exclusively owned by `worker_r2_1` during M2 implementation: all files under `<REPO_ROOT>/` (`cxas_app/`, `lib/`, `evals/`, `tests/`, `scripts/`, `eval-reports/`).
