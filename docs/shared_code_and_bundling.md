# Shared Code, Prompt Bundling & PIF Structure (`docs/shared_code_and_bundling.md`)

This guide explains why files inside [`cxas_app/`](../cxas_app) must be self-contained, how we avoid copy-paste drift across agents and tools using our **marker-region bundler** ([`scripts/bundle_shared_imports.py`](../scripts/bundle_shared_imports.py)), and how every agent prompt is organized using the **Programmatic Instruction Following (PIF XML)** structure.

---

## 1. Why Bundling Exists (The CXAS Sandbox Rule)

When Google Cloud Customer Engagement Suite / Conversational Agent Studio (**CXAS**) executes a tool function (`cxas_app/tools/<tool>/python_function/python_code.py`) or an agent callback (`cxas_app/agents/<agent>/<callback_type>/<callback>/python_code.py`) in the cloud:
- Each `python_code.py` file is uploaded and executed inside an **isolated single-file cloud sandbox**.
- That cloud sandbox only receives the single `python_code.py` script—it does **not** have access to our local git repository folders like `lib/` or `totto_suite/`.
- Similarly, each agent's instruction file (`cxas_app/agents/<agent>/instruction.txt`) is validated by `cxas lint` Rule `I001` and sent to the language model as a standalone text file without any server-side `#include` mechanism.

If we wrote `from lib.shared_python.openf1_http import _fetch_openf1_json` inside a tool file, it would work on a developer's laptop and then crash in the cloud with `ModuleNotFoundError: No module named 'lib'`. Conversely, if we manually copy-pasted shared code or shared persona rules into 11 different files, someone would inevitably edit one copy and forget the others.

---

## 2. How `scripts/bundle_shared_imports.py` Works (Marker-Region Text Bundler)

To get the best of both worlds—**single-source-of-truth editing in [`lib/`](../lib)** and **100% self-contained files in [`cxas_app/`](../cxas_app)**—we use [`scripts/bundle_shared_imports.py`](../scripts/bundle_shared_imports.py).

> [!NOTE]
> **How the bundler works under the hood**: [`scripts/bundle_shared_imports.py`](../scripts/bundle_shared_imports.py) is a deterministic **marker-region text bundler** (not an abstract syntax tree / AST rewriter). It locates explicit `<persona>...</persona>` or `# >>> BEGIN SHARED ... <<<` / `# >>> END SHARED ... <<<` markers inside target files and replaces the text between those markers with the exact contents of the canonical source file in `lib/`.

### The 3 Shared Regions Synchronized Across 11 Target Files

| Region Name | Canonical Source File in `lib/` | Markers in Target Files | Target Files in `cxas_app/` (11 Total) |
| :--- | :--- | :--- | :--- |
| **`persona`** | [`lib/shared_prompts/persona.txt`](../lib/shared_prompts/persona.txt) | `<persona>` ... `</persona>` | **5 instruction files**:<br/>• [`cxas_app/global_instruction.txt`](../cxas_app/global_instruction.txt)<br/>• [`cxas_app/agents/totto_root_agent/instruction.txt`](../cxas_app/agents/totto_root_agent/instruction.txt)<br/>• [`cxas_app/agents/race_info_agent/instruction.txt`](../cxas_app/agents/race_info_agent/instruction.txt)<br/>• [`cxas_app/agents/merch_support_agent/instruction.txt`](../cxas_app/agents/merch_support_agent/instruction.txt)<br/>• [`cxas_app/agents/ticketing_agent/instruction.txt`](../cxas_app/agents/ticketing_agent/instruction.txt) |
| **`openf1_http`** | [`lib/shared_python/openf1_http.py`](../lib/shared_python/openf1_http.py) | `# >>> BEGIN SHARED openf1_http: generated from lib/shared_python/openf1_http.py by scripts/bundle_shared_imports.py. Edit the lib/ file, not this copy. <<<`<br/>...<br/>`# >>> END SHARED openf1_http <<<` | **2 OpenF1 tool files**:<br/>• [`cxas_app/tools/get_race_schedule/python_function/python_code.py`](../cxas_app/tools/get_race_schedule/python_function/python_code.py)<br/>• [`cxas_app/tools/get_driver_standings/python_function/python_code.py`](../cxas_app/tools/get_driver_standings/python_function/python_code.py) |
| **`voice_sanitizer`** | [`lib/shared_python/voice_sanitizer.py`](../lib/shared_python/voice_sanitizer.py) | `# >>> BEGIN SHARED voice_sanitizer: generated from lib/shared_python/voice_sanitizer.py by scripts/bundle_shared_imports.py. Edit the lib/ file, not this copy. <<<`<br/>...<br/>`# >>> END SHARED voice_sanitizer <<<` | **4 agent `after_model_callbacks`**:<br/>• [`cxas_app/agents/totto_root_agent/after_model_callbacks/voice_sanitizer/python_code.py`](../cxas_app/agents/totto_root_agent/after_model_callbacks/voice_sanitizer/python_code.py)<br/>• [`cxas_app/agents/race_info_agent/after_model_callbacks/voice_sanitizer/python_code.py`](../cxas_app/agents/race_info_agent/after_model_callbacks/voice_sanitizer/python_code.py)<br/>• [`cxas_app/agents/merch_support_agent/after_model_callbacks/voice_sanitizer/python_code.py`](../cxas_app/agents/merch_support_agent/after_model_callbacks/voice_sanitizer/python_code.py)<br/>• [`cxas_app/agents/ticketing_agent/after_model_callbacks/voice_sanitizer/python_code.py`](../cxas_app/agents/ticketing_agent/after_model_callbacks/voice_sanitizer/python_code.py) |

### Why `openf1_http` Is Placed *Below* the Main Tool Function (`cxas lint` Rule `T004`)
In CXAS tool files (`cxas_app/tools/<tool>/python_function/python_code.py`), the official `cxas lint` validator enforces **Rule `T004`**: the **first** top-level `def` statement in the file must be the tool entrypoint function whose name matches the tool directory (i.e., `def get_race_schedule(...)` or `def get_driver_standings(...)`).
- Because Python resolves helper functions when the entrypoint function is *called* (not when `def` is parsed), placing the `# >>> BEGIN SHARED openf1_http ... <<<` region **below** `def get_race_schedule` / `def get_driver_standings` keeps the tool entrypoint as the first function in the file and passes `cxas lint` with zero warnings.

---

## 3. Developer Workflow: Editing Shared Prompts or Python Helpers

Whenever you want to change the shared Totto persona, the OpenF1 HTTP client helper, or the voice markdown sanitizer:

1. **Edit the canonical source file in `lib/`**:
   - Persona & non-impersonation rules: [`lib/shared_prompts/persona.txt`](../lib/shared_prompts/persona.txt)
   - OpenF1 HTTP client (`OPENF1_BASE_URL`, `_get_cache`, `_fetch_openf1_json`): [`lib/shared_python/openf1_http.py`](../lib/shared_python/openf1_http.py)
   - Markdown-stripping callback helper (`clean_spoken_text`, `after_model_callback`): [`lib/shared_python/voice_sanitizer.py`](../lib/shared_python/voice_sanitizer.py)
2. **Synchronize all 11 target files in `cxas_app/`**:
   ```bash
   .venv/bin/python scripts/bundle_shared_imports.py
   ```
3. **Verify zero drift**:
   ```bash
   make bundle
   # (equivalent to: .venv/bin/python scripts/bundle_shared_imports.py --check)
   ```

### How CI & Mutants Enforce Zero Drift
- **Unit Test**: `test_shared_regions_in_sync_with_lib` in [`tests/config/test_agent_instructions_and_contracts.py`](../tests/config/test_agent_instructions_and_contracts.py) runs during `totto_suite offline` (Layer 2: `config`) and fails immediately if any of the 11 files in `cxas_app/` drift by even a single character from `lib/`.
- **Fault-Injection Mutants**: `mutant_bundle_persona_drift` and `mutant_bundle_openf1_helper_drift` in [`totto_suite/mutants.py`](../totto_suite/mutants.py) deliberately modify a bundled region inside `cxas_app/` without running `bundle_shared_imports.py`, proving that the offline gate catches unbundled edits (`15/15` mutants killed).

---

## 4. Programmatic Instruction Following (PIF XML) Structure

Every agent prompt (`cxas_app/agents/<agent>/instruction.txt`) and the global instruction file ([`cxas_app/global_instruction.txt`](../cxas_app/global_instruction.txt)) follow a strict XML structure enforced by [`tests/config/test_agent_instructions_and_contracts.py`](../tests/config/test_agent_instructions_and_contracts.py):

### 4.1 Global Instructions ([`cxas_app/global_instruction.txt`](../cxas_app/global_instruction.txt))
Applies to all 4 agents in the app and contains:
- **`<persona>`**: Synchronized from [`lib/shared_prompts/persona.txt`](../lib/shared_prompts/persona.txt). Establishes Totto as **Totto, Mercedes F1 Fan Agent** (never claiming to be the real Toto Wolff), sets 2026 Silver Arrows context (George Russell in car 63 and Kimi Antonelli in car 12), and mandates brand-safe respect toward rival teams and officials.
- **Global Rules & `<guidelines>`**: Enforces multilingual language continuity (`AC-6`), tool-grounding integrity (`TR-01`), silent handoffs (`TR-03`), and voice-first spoken guidelines (2–3 short sentences, ~300 characters, plain prose without markdown symbols, speaking `"car 63"` instead of `"#63"`, and speaking short domain names `shop.mercedesamgf1.com` and `tickets.formula1.com`).

### 4.2 Individual Agent Instructions (`cxas_app/agents/<agent>/instruction.txt`)
Each of the 4 agent `instruction.txt` files contains 5 required top-level XML blocks:
1. **`<role>`**: Defines the specific agent's mission and scope boundary.
2. **`<persona>`**: Contains the bundled `<persona>...</persona>` block from [`lib/shared_prompts/persona.txt`](../lib/shared_prompts/persona.txt).
3. **`<constraints>`**: Hard rules the agent must never violate (for example, never fabricating schedules or order statuses, never impersonating Toto Wolff, never emitting markdown formatting, and never accepting credit card numbers).
4. **`<taskflow>`**: Structured `<subtask>` and `<step>` blocks describing which tool to call for each user intent and when to transfer to another agent.
5. **`<examples>`**: Compact, 1–2 turn routing and tool-invocation examples written in plain spoken prose without hardcoded multi-turn lookup tables (`TR-01`).
