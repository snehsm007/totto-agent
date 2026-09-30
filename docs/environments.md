# Environments, Configuration & Secret Hygiene (`environments.md`)

This guide explains how the **Totto Agent** separates its **Staging** and **Live Production** cloud environments, how configuration works on your local laptop versus GitHub Actions CI, and how we keep project IDs, app UUIDs, and credentials out of git.

---

## 1. Two Cloud Environments: Staging vs. Live Production

We maintain two separate Customer Experience Agent Studio (**CXAS**) applications in Google Cloud so experimental changes and pull requests never touch the live agent or the public telephone line (`+1 218-288-9381`) until they pass every automated check:

| Environment | GitHub Actions Variable | Who Pushes to It | Purpose |
| :--- | :--- | :--- | :--- |
| **Staging App** | `CXAS_STAGING_APP_ID` | GitHub Actions `staging-gate` job (on every PR and every push to `main`) | Scratchpad cloud environment where `scripts/ci/push_app.py` pushes the candidate `cxas_app/` bundle, `totto_suite ci-gate` runs cloud tool/golden/simulation gates, and `totto_suite verify-ids` verifies server resource IDs. |
| **Live Production App** | `CXAS_LIVE_APP_ID` | GitHub Actions `deploy-live` job (**only** on `refs/heads/main` after `staging-gate` passes) | Production environment backing the live agent and the **Google Telephony Platform (`+1 218-288-9381`)** phone line. Every deployment creates an immutable version named `git-<sha7>` (`--create-version`) and records a before/after snapshot diff. |

---

## 2. How Configuration Is Loaded (Zero Hardcoded IDs in Git)

No file tracked in git contains a hardcoded Google Cloud Project ID, project number, or CXAS App UUID. Instead, [`totto_suite/deploy.py`](../totto_suite/deploy.py) (`load_gecx_config()`) resolves target environment settings in the following priority order:

### Priority 1: Explicit CLI Flags & Environment Variables (Used in CI)
In GitHub Actions ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) or shell scripts, you can pass explicit flags or environment variables without creating any config file on disk:
- `--app-name` CLI flag (accepted by `scripts/ci/push_app.py`, `scripts/ci/deploy_live.py`, `totto_suite ci-gate`, and `totto_suite verify-ids`)
- `TOTTO_APP_NAME`: Full CXAS resource path (`projects/<PROJECT_ID>/locations/<REGION>/apps/<APP_UUID>`)
- `GCP_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`): Overrides project ID
- `CXAS_STAGING_APP_ID` / `CXAS_LIVE_APP_ID`: Used by CI jobs to target staging vs. live apps
- `CXAS_EVAL_AUDIO_BUCKET`: Optional GCS bucket name (without `gs://`) injected by [`scripts/ci/push_app.py`](../scripts/ci/push_app.py) into a temporary staging copy of `cxas_app/app.json` as `evaluationAudioRecordingConfig.gcsUri` (`gs://<bucket>/eval-audio`)

### Priority 2: Local Gitignored `gecx-config.json` (Used for Local Cloud Inspection)
For local developer commands that read from the cloud (such as `python -m totto_suite deploy --snapshot`), create a local `gecx-config.json` file in the repository root by copying [`gecx-config.example.json`](../gecx-config.example.json):

```bash
cp gecx-config.example.json gecx-config.json
```

Example `gecx-config.json` structure (this file is listed in [`.gitignore`](../.gitignore) and is **never** committed):
```json
{
  "project_id": "your-gcp-project-id",
  "location": "us-central1",
  "app_id": "00000000-0000-0000-0000-000000000000",
  "staging_app_id": "11111111-1111-1111-1111-111111111111",
  "eval_audio_bucket": "your-optional-eval-audio-gcs-bucket",
  "live_gtp_deployment_id": "projects/your-gcp-project-id/locations/us-central1/apps/00000000-0000-0000-0000-000000000000/deployments/22222222-2222-2222-2222-222222222222"
}
```

> [!TIP]
> **Running Offline Checks Requires Zero Cloud Config**: You do **not** need `gecx-config.json` or Google Cloud credentials to run `make check` (`totto_suite offline`), `make mutants` (`totto_suite mutants`), or `make test` (`pytest`). All 410 offline checks and 15 fault-injection mutants run 100% locally in ~15 seconds.

---

## 3. App-Relative Resource IDs in Committed History (`evals/history/`)

When `totto_suite ci-gate` records an evaluation run under [`evals/history/runs/`](../evals/history/runs/), it scrubs full Google Cloud resource paths before writing `summary.json` and `details.json` to disk:
- Full server path returned by CXAS API:
  `projects/<PROJECT_ID>/locations/us-central1/apps/<APP_UUID>/evaluationRuns/<RUN_UUID>`
- Scrubbed **app-relative ID** stored in git:
  `evaluationRuns/<RUN_UUID>` (paired with `"app_ref": "staging"` or `"app_ref": "live"`).

Similarly, conversation transcripts store `conversations/<CONV_UUID>` and deployed versions store `versions/<VERSION_UUID>`. When `python -m totto_suite verify-ids --app-name "$CXAS_STAGING_APP_ID" --run-id "$RUN_ID"` runs, [`totto_suite/verify_ids.py`](../totto_suite/verify_ids.py) rehydrates those app-relative IDs with `--app-name` to verify each resource on the server without leaking project or app identifiers into git history.

---

## 4. Automated Privacy & Identifier Scrubbing

Three independent layers verify that internal project IDs, project numbers, service accounts, or developer usernames never leak into the repository or the public dashboard:
1. **Committed History Scrubber**: [`totto_suite/ci_gate.py`](../totto_suite/ci_gate.py) (`to_app_relative_id()`) converts all `projects/.../apps/.../` prefixes to app-relative paths at write time.
2. **Dashboard Build Scrubber**: [`totto_suite/dashboard/scrub.py`](../totto_suite/dashboard/scrub.py) scans every generated HTML/JSON byte when `python -m totto_suite dashboard build` runs, replacing any `projects/...` resource paths, project numbers, or emails and failing the build if any forbidden identifier remains.
3. **Acceptance Test Gate**: [`tests/acceptance/test_acceptance_criteria.py`](../tests/acceptance/test_acceptance_criteria.py) scans `cxas_app/`, `README.md`, and `docs/` on every test run to guarantee zero leaked project IDs or usernames.
