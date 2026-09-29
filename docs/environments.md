# Environment & Operations Guide

> 📖 **Enterprise Architecture Blueprint Series**:  
> [Overview](../README.md) • [🗣️ Architecture](architecture.md) • [📦 Shared Code & DRY](shared_code_and_bundling.md) • [🌐 Environments](environments.md) • [🚀 CI/CD & Mutants](ci-cd.md) • [📊 Simulation Dashboard](simulation_dashboard.md) • [🔍 Conversation Inspection](conversation_inspection.md) • [🎓 Knowledge Share](knowledge_share_guide.md)

This repository decouples **GCP deployment topology metadata** (project IDs, regions, and CX Agent Studio app UUIDs) from tracked source code so that zero project or environment details are exposed in Git commits.

---

## 📁 Directory Structure

```
totto-agent/
├── gecx-config.example.json               # Root config template (tracked in Git)
├── gecx-config.json                       # Local active config (GITIGNORED)
└── environments/
    ├── dev-totto-gecx/
    │   ├── gecx-config.example.json       # Dev tier template (tracked in Git)
    │   └── gecx-config.json               # Local dev config (GITIGNORED)
    ├── staging-totto-gecx/
    │   ├── gecx-config.example.json       # Staging tier template (tracked in Git)
    │   └── gecx-config.json               # Local staging config (GITIGNORED)
    └── local-<user>-totto-gecx/           # Personal developer sandbox (GITIGNORED)
        └── gecx-config.json
```

---

## ⚙️ Environment Configuration Schema (`gecx-config.json`)

To configure your local workspace for live cloud deployment or evaluation, copy `gecx-config.example.json` to `gecx-config.json` (or `environments/dev-totto-gecx/gecx-config.json`) and populate your target GCP project and CXAS application UUID:

```json
{
  "gcp_project_id": "<YOUR_GCP_PROJECT_ID>",
  "location": "us",
  "deployed_app_id": "<YOUR_CXAS_APP_UUID>",
  "app_id": "<YOUR_CXAS_APP_UUID>",
  "app_name": "totto-mercedes-f1-fan-agent",
  "app_dir": "cxas_app",
  "modality": "text",
  "default_channel": "text"
}
```

| Field | Description |
|---|---|
| `gcp_project_id` | GCP Project ID hosting your CX Agent Studio (CES / GECX) application |
| `location` | GCP region / multi-region (e.g., `us`) |
| `deployed_app_id` / `app_id` | Application UUID in Google Cloud CES |
| `app_name` | Display name for the agent application (`totto-mercedes-f1-fan-agent`) |
| `app_dir` | Local agent source directory (`cxas_app`) |
| `modality` | Default interaction channel modality (`text` or `audio`) |

---

## 🔒 Privacy & Security Policy

1. **Gitignored Local Configs**: Both `gecx-config.json` and `environments/**/gecx-config.json` are excluded in [`.gitignore`](../.gitignore). Your personal GCP project ID and app UUID stay strictly on your local machine.
2. **Environment Variable Overrides**: You can also override the target application at runtime without editing any file:
   ```bash
   export TOTTO_APP_NAME="projects/<YOUR_GCP_PROJECT_ID>/locations/us/apps/<YOUR_CXAS_APP_UUID>"
   ```
3. **Zero-Config Offline Execution**: All 8 offline verification layers (`make offline`, `make gate`, `make mutants`, `make test`) run 100% hermetically against `cxas_app/` and `tests/fixtures/` without requiring a `gecx-config.json` or active GCP credentials.
4. **Authentication**: Live commands (`make live`, `make deploy`, `totto_suite snapshot`) use Google Cloud **Application Default Credentials (ADC)** locally (`gcloud auth application-default login`) or **Workload Identity Federation (WIF)** in CI. Never place service account keys or bearer tokens in any repository file.
