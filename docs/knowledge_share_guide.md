# Knowledge Share & Handover Guide (`docs/knowledge_share_guide.md`)

This guide provides a structured walkthrough for engineers, reviewers, or stakeholders picking up the **Totto Agent** project. It summarizes what was broken in the original baseline agent, how each engineering pillar solved those defects, and how to demo or extend the system in minutes.

---

## 1. Executive Summary: From Broken Baseline to Production-Grade Agent

**Totto, Mercedes F1 Fan Agent** is a multi-agent voice and chat assistant for **Mercedes-AMG PETRONAS Formula One Team** fans built on Google Cloud Customer Engagement Suite / Conversational Agent Studio (**CXAS**).

When we inherited the initial prototype, a comprehensive audit (cataloged in [`docs/COVERAGE.md`](COVERAGE.md) and [`docs/DEFECTS.md`](DEFECTS.md) across findings `TR-01..TR-10`, `TB-1..TB-5`, `RC-01..RC-13`, and `NEW-1..NEW-5`) uncovered major reliability, accuracy, and operations gaps. Here is how the system compares before and after our engineering remediation:

| Dimension | Initial Prototype Baseline | Current Production State (`HEAD`) |
| :--- | :--- | :--- |
| **Offline Verification (`make offline`)** | Ad-hoc manual testing; no automated prompt, callback, or timezone checks | **8-layer offline suite (`410/410` checks passing in ~14s)** + **526+ pytest tests** |
| **Fault-Injection Mutation Score (`make mutants`)** | 0 mutants; no proof that tests catch regressions | **15/15 (100.0%) offline mutants killed** + **1 live cloud staging mutant** (`race_schedule_blackout.patch`) proven to block CI |
| **Cloud Staging Gate & CI/CD** | Manual `cxas push` from developer laptops; no staging gate | **4-job GitHub Actions pipeline** ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) with keyless WIF auth, `"CXAS eval gate"` on Staging, `verify-ids`, and automated Live deploy (`git-<sha7>`) |
| **Tool Reliability & `toolFakeConfig`** | Tools failed when OpenF1 was blocked in sandbox (`TB-1`), silently returned Round 1 Australia for unknown races (`TB-3`), failed on `category="both"` (`TR-08`), used hardcoded UTC offsets (`TR-10`), and had no `toolFakeConfig` | All 4 tools have resilient fallbacks, ~600 `zoneinfo` IANA DST timezones, verified official links (`get_official_links`), and dual-mode **`toolFakeConfig`** (`enableFakeMode: true`) |
| **Voice & Live Telephone Channel** | Prompts emitted markdown (`**bold**`, bullets, `#63`) that broke Text-to-Speech; no phone channel | Plain-prose voice prompts + **`voice_sanitizer`** `after_model_callback` on all 4 agents + live PSTN phone line **`+1 218-288-9381`** (`GOOGLE_TELEPHONY_PLATFORM`) + `evaluationAudioRecordingConfig` |
| **Public Observability** | Raw JSON files on disk | Live scrubbed dashboard at **[`https://snehsm007.github.io/totto-agent/`](https://snehsm007.github.io/totto-agent/)** across **30 recorded runs** |

---

## 2. 5-Minute Live Demo & Walkthrough Script

If you are presenting or reviewing this project, follow these 5 steps in order:

### Step 1: Open the Live Public Dashboard (30 seconds)
- Open **[`https://snehsm007.github.io/totto-agent/`](https://snehsm007.github.io/totto-agent/)** (or the mirror at [`https://raw.githack.com/snehsm007/totto-agent/dashboard/index.html`](https://raw.githack.com/snehsm007/totto-agent/dashboard/index.html)).
- Point out the **Live Production Banner** showing the active immutable version (`git-<sha7>`), the live phone number **`+1 218-288-9381`**, the **pass-rate trend chart** across all recorded runs (including the intentional red `FAIL` run where the staging gate caught the injected live mutant), and the per-layer breakdown.

### Step 2: Call the Live Agent on `+1 218-288-9381` (1 minute)
- Dial **`+1 218-288-9381`** from any phone.
- Ask:
  1. *"Who is leading the 2026 drivers' championship right now?"* (Routes silently to `race_info_agent` $\rightarrow$ calls `get_driver_standings` $\rightarrow$ speaks Kimi Antonelli in car 12 with 302 points and George Russell in car 63 with 236 points in clean, natural sentences without markdown artifacts.)
  2. *"When is the next race, and what time is it in London?"* (`race_info_agent` calls `get_race_schedule(race_name="next", user_timezone="London")` and speaks the converted local session times.)
  3. *"Can you check on my merch order 1001?"* (Transfers silently to `merch_support_agent` $\rightarrow$ calls `lookup_mock_merch_order` $\rightarrow$ reports the simulated George Russell cap order was delivered via DHL Express.)

### Step 3: Run the 410-Check Offline Suite Locally (30 seconds)
```bash
make offline
```
- Show the terminal table completing all **8 layers (`lint`, `config`, `callbacks`, `tools`, `dates`, `grader`, `regrade`, `selftest`) — 410/410 PASS** in ~14 seconds without needing cloud credentials.

### Step 4: Run the 15-Mutant Fault-Injection Harness (1 minute)
```bash
make mutants
```
- Show `totto_suite mutants` injecting 15 realistic bugs across tools, callbacks, and prompts—and killing **15/15 (100.0%)**.

### Step 5: Walk Through the 4-Job GitHub Actions CI/CD Pipeline (1 minute)
- Open [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) and [`docs/ci-cd.md`](ci-cd.md) to show how every commit flows through `offline` $\rightarrow$ `staging-gate` (step `"CXAS eval gate"` + `verify-ids`) $\rightarrow$ `deploy-live` (`git-<sha7>` + `+1 218-288-9381` repoint) $\rightarrow$ `publish-dashboard`.

---

## 3. Historical Context Note on Pre-Squash Commit SHAs

When browsing [`docs/COVERAGE.md`](COVERAGE.md), [`docs/DEFECTS.md`](DEFECTS.md), [`evals/history/index.json`](../evals/history/index.json), or [`evals/history/snapshots/`](../evals/history/snapshots), you will see short commit SHAs from earlier development rounds (such as `bdb8f3b`, `1a17988`, `a7c3094`, `6a4d0d2`, `fd9be8b`, or `95d3ccf`) that were recorded at the moment those evaluation runs or cloud snapshots were captured. Those historical commit references are preserved as immutable audit evidence of how the agent progressed from its initial baseline to `100.0%` (`410/410` offline checks and `15/15` mutants killed).

---

## 4. Where to Go Next

- **System Architecture & Voice/PSTN Design**: [`docs/architecture.md`](architecture.md)
- **CI/CD Pipeline, Gate Thresholds & Live Mutant Proof**: [`docs/ci-cd.md`](ci-cd.md)
- **Shared `lib/` Code & Marker-Region Bundler (`make bundle`)**: [`docs/shared_code_and_bundling.md`](shared_code_and_bundling.md)
- **Cloud Environments & Secret Hygiene**: [`docs/environments.md`](environments.md)
- **Public Dashboard & Trend Reports**: [`docs/simulation_dashboard.md`](simulation_dashboard.md)
- **Transcript Grader & Server ID Verification**: [`docs/conversation_inspection.md`](conversation_inspection.md)
- **23-Finding Traceability Matrix (`TR-01..TR-10`, `RC-01..RC-13`)**: [`docs/COVERAGE.md`](COVERAGE.md)
- **Baseline Live Defect Log**: [`docs/DEFECTS.md`](DEFECTS.md)
