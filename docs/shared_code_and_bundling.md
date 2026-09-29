# Shared Code, Prompt Synchronization & Single-File Serverless Bundling

## 1. Why Single-File Bundling Matters in CX Agent Studio (CES)

Google Cloud CX Agent Studio executes each Python tool (`cxas_app/tools/<name>/python_function/python_code.py`), tool fake (`tool_fake_config/code_block/python_code.py`), and callback (`before_agent_callbacks` / `after_tool_callbacks`) inside an isolated serverless sandbox.

- **No Cross-File Python Imports at Runtime**: Relative or repo-root imports (such as `from lib.helpers import ...`) fail inside the cloud sandbox because only the individual `python_code.py` file is uploaded per resource.
- **No `from __future__ import annotations` in Callbacks**: CES wraps callback code inside an internal runner function before compilation; placing `from __future__ import ...` at the top of a callback causes a `SyntaxError: from __future__ imports must occur at the beginning of the file` on the platform.
- **Synchronized Multi-Agent Persona**: All 4 agents (`totto_root_agent`, `race_info_agent`, `merch_support_agent`, `ticketing_agent`) must share the exact same brand voice, AI transparency disclosure, and rivalry-respect rules without drifting out of sync.

```
┌────────────────────────────────────────────────────────────┐
│  Canonical Shared Source (lib/ & scripts/)                 │
│  ├── lib/shared_prompts/persona.txt                        │
│  └── scripts/bundle_shared_imports.py                      │
└─────────────────────────────┬──────────────────────────────┘
                              │ make bundle (--check in CI / gate)
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ Self-Contained Python Tools   │ │ Synchronized Agent Prompts    │
│ & Tool Fakes (cxas_app/tools/)│ │ (cxas_app/agents/*/...)       │
│ • Zero external repo imports  │ │ • PIF XML (<role>, <persona>, │
│ • Embedded 2026 F1 fallback   │ │   <constraints>, <taskflow>,  │
│ • Deterministic fake_tool_call│ │   <examples>)                 │
└───────────────────────────────┘ └───────────────────────────────┘
```

---

## 2. Prompt Synchronization (`scripts/bundle_shared_imports.py`)

Canonical persona rules live in [`lib/shared_prompts/persona.txt`](../lib/shared_prompts/persona.txt) and are synchronized with the `<persona>...</persona>` block in [`cxas_app/agents/totto_root_agent/instruction.txt`](../cxas_app/agents/totto_root_agent/instruction.txt).

### Commands

```bash
# Verify that shared prompts and agent instructions are in sync (exits 1 on drift)
.venv/bin/python scripts/bundle_shared_imports.py --check

# Or via Makefile:
make bundle
```

### Automated Enforcement

Two independent offline checks enforce synchronization on every run and commit:
1. **`lint` Layer ([`totto_suite/layers/offline_lint.py`](../totto_suite/layers/offline_lint.py))**: Runs `scripts/bundle_shared_imports.py --check` alongside `cxas lint`.
2. **`config` Layer ([`tests/config/test_agent_instructions_and_contracts.py`](../tests/config/test_agent_instructions_and_contracts.py))**: `test_callbacks_synced_with_shared_imports` verifies exit code `0`.

---

## 3. Prompt Instruction Format (PIF) XML Contract

Every agent instruction file (`cxas_app/agents/<agent>/instruction.txt`) is statically verified against the following contract in [`tests/config/test_agent_instructions_and_contracts.py`](../tests/config/test_agent_instructions_and_contracts.py):

- **Required XML Sections**: `<role>`, `<persona>`, `<constraints>`, `<taskflow>` (containing `<subtask>` and `<step>`), and `<examples>`.
- **Mandatory `{current_date}` Placeholder**: Every agent `<role>` block includes `{current_date}` (`cxas lint` rule `I014`).
- **Banned Legacy Tags**: `<context>`, `<state>`, `<transitions>`, `<reasoning>`, and `<thought>` are prohibited (`cxas lint` rule `I015`).
- **Bidirectional Tool Reference Check (`I012` / `I013`)**: Every non-terminal tool listed in `<agent>.json` must be referenced via `{@TOOL: <name>}` in `instruction.txt`, and every `{@TOOL: <name>}` or `{@AGENT: <name>}` reference must exist in the agent's JSON configuration.
- **Anti-Hallucination & Anti-Leak Example Hygiene**: `<examples>` blocks use structural placeholders (`<ORDER_ID_FROM_TOOL>`, `<RACE_NAME_FROM_TOOL>`) and are tested against [`evals/probes/probes.yaml`](../evals/probes/probes.yaml) and [`evals/goldens/goldens.yaml`](../evals/goldens/goldens.yaml) so literal test prompts or fake tracking numbers (`DHL-9928174`) can never be memorized from examples.
