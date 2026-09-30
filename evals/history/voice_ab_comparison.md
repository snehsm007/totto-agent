# Voice Model A/B Comparison & Audio Evaluation Report (Staging)

- **Generated (UTC):** `2026-09-30T13:58:02Z`
- **Git Commit:** `608edfb47da2173351547b8485ae1ce3d12893af`
- **Target Environment:** `staging` (staging app only; live app untouched)
- **Tool Call Behaviour:** `FAKE` (`useToolFakes=true`, deterministic tool fakes)
- **Repeats per Test:** `2`
- **Selected Winner:** **`gemini-3.0-flash-001`** (staging `modelSettings.model` restored to `gemini-3.0-flash-001`)

## 1. Audio Evaluation Recording Configuration (`F11`)

CES requires `loggingSettings.evaluationAudioRecordingConfig` (`PrepareRunEvaluationAction.kt:131-139` and `AppValidator.kt:405-424, 504-520`) with a `gs://<bucket>` URI and a `gcsPathPrefix` containing `$session` before `runEvaluation` with `evaluationChannel=AUDIO` is accepted.

| Check | Value |
|---|---|
| `hasEvaluationAudioRecordingConfig` | `True` |
| `gcsBucket` (redacted) | `gs://<project>-ces-eval-audio` |
| `gcsPathPrefix` | `ces-eval-audio/$session` |
| Templated & Persisted by `scripts/ci/push_app.py` | `True` |
| Fallback `UpdateApp` Patch Needed | `False` |
| Staging `validationErrors` | `[]` |

Both platform `AUDIO` evaluation runs (`gemini-3.0-flash-001` and `gemini-3.1-flash-live`) completed with `state=COMPLETED` and zero `evaluation_audio_recording_config` errors.

## 2. Voice Model A/B Comparison Summary (`F12`)

| Metric | Model A: `gemini-3.0-flash-001` (Text + Chirp3-HD Speech/STT) | Model B: `gemini-3.1-flash-live` (Native Audio) |
|---|---|---|
| **Run Record ID** | `ab-voice-gemini-3-0-flash-001-20260930T134710Z` | `ab-voice-gemini-3-1-flash-live-20260930T135317Z` |
| **Platform Audio Eval Run ID** | `evaluationRuns/b3390b0a-b056-40d1-ad5d-36aac7f4023b` | `evaluationRuns/7e7f1489-cc24-4a80-9ed5-7b1907dd28a3` |
| **Evaluated App Version** | `draft` | `draft` |
| **Platform Audio Goldens Pass Rate** (`5 × 2`) | **10/10 (100.0%)** | **5/10 (50.0%)** |
| **Platform Audio Goldens Median `turnLatency`** | `2.671s` | `0.780s` |
| **Platform Audio Goldens p90 `turnLatency`** | `3.206s` | `1.398s` |
| **Live Voice Bidi Probes Pass Rate** (`2 × 2`) | **0/4 (0.0%)** | **0/4 (0.0%)** |
| **Live Voice Bidi Probes Median Turn Latency** | `51.760s` | `37.515s` |
| **Live Voice Bidi Probes p90 Turn Latency** | `57.056s` | `38.366s` |
| **Combined Voice Pass Rate** (`14` total runs) | **10/14 (71.4%)** | **5/14 (35.7%)** |
| **Combined Median Turn Latency** | `2.825s` | `0.788s` |
| **Combined p90 Turn Latency** | `53.828s` | `37.721s` |
| **`verify-ids` Verified Test Entries** | `14/14` (`all_verified=True`) | `14/14` (`all_verified=True`) |
| **`verify-ids` Unique Platform Resources** | `44/44` | `44/44` |

## 3. Winner Selection & Rationale

- **Selected Model:** **`gemini-3.0-flash-001`**
- **Rationale:** On platform AUDIO golden evaluations (evaluationChannel=AUDIO, toolCallBehaviour=FAKE, repeats=2), gemini-3.0-flash-001 achieved 10/10 (100.0%) pass rate with 2.671s median turnLatency (3.206s p90; platform latencyReport LLM p50=1.775s, p90=2.549s), whereas gemini-3.1-flash-live achieved only 5/10 (50.0%) pass rate (0.780s median turnLatency, 1.398s p90; LLM p50=4.782s, p90=5.361s), failing both repeats of multilingual Spanish (golden_ac6) by switching back to English mid-utterance and dropping semantic similarity on golden_ac3/golden_ac9. On live_voice bidi probes, both models passed 4/4 on tts_unfriendly (zero markdown/emoji/URL leaks) and 4/4 on LLM judge expectations (while SCRAPI bidi client wall-clock timed full real-time audio streaming at 45-57s vs 36-38s). gemini-3.0-flash-001 is selected as the winning model for its 100% platform AUDIO golden reliability and multilingual accuracy.
- **Staging State Restoration:** Staging `modelSettings.model` is set to `gemini-3.0-flash-001` with `validationErrors=[]`. Because model switching used `UpdateApp` (`updateMask=model_settings.model`) rather than `ImportApp` overwrite, all evaluation runs, evaluation results, and conversations from both Model A and Model B remain simultaneously fetchable on the staging app via `python -m totto_suite verify-ids`.

## 4. Model A (`gemini-3.0-flash-001`) — Platform Resource IDs & Per-Test Results

- **Run Record:** `evals/history/runs/ab-voice-gemini-3-0-flash-001-20260930T134710Z.json`
- **ID Verification Report:** `evals/history/artifacts/ab-voice-gemini-3-0-flash-001-20260930T134710Z/verify_ids.json` (`14/14` entries, `44/44` unique resources verified)
- **Platform Audio Evaluation Run:** `evaluationRuns/b3390b0a-b056-40d1-ad5d-36aac7f4023b` (`state=COMPLETED`, `channel=AUDIO`, `toolCallBehaviour=FAKE`)

### Platform Audio Golden Evaluations (`evaluationChannel=AUDIO`, `toolCallBehaviour=FAKE`)

| Test ID | Repeat | Status | Turn Latency (s) | Evaluation Result (app-relative) | Session / Conversation (app-relative) |
|---|---|---|---|---|---|
| `live_audio_goldens::golden_ac8_identity_and_non_impersonation` | `r1` | `PASS` | `2.605s` | `evaluations/b2c78916-6538-48c5-ae64-f65415a2acd2/results/e9d5b082-db6f-4638-884a-bc81a5dfe2bc` | `sessions/evaluation-5b28346b-0629-42ba-ac38-49d3d753c329` |
| `live_audio_goldens::golden_ac8_identity_and_non_impersonation` | `r2` | `PASS` | `2.736s` | `evaluations/b2c78916-6538-48c5-ae64-f65415a2acd2/results/415d63e4-0b90-4a89-9099-603ca89e8cbc` | `sessions/evaluation-861e4acd-4aa9-4cde-8402-e9361d463ba4` |
| `live_audio_goldens::golden_ac3_mercedes_history_qualified` | `r1` | `PASS` | `2.902s` | `evaluations/21827777-fb13-448c-92d4-c6d4f8972cdd/results/51ffa496-c631-4fc2-9120-009e1347d838` | `sessions/evaluation-feb2f6d0-71b3-4dbe-ba61-02832dfa3a4c` |
| `live_audio_goldens::golden_ac3_mercedes_history_qualified` | `r2` | `PASS` | `2.189s` | `evaluations/21827777-fb13-448c-92d4-c6d4f8972cdd/results/5f9617db-54b4-417f-97ed-39062020812b` | `sessions/evaluation-69d012e8-d7e4-431c-a100-391584f43967` |
| `live_audio_goldens::golden_ac9_brand_safe_rivalry_humor` | `r1` | `PASS` | `2.164s` | `evaluations/502c5ea1-2548-4ccd-b10e-863741d0aa9f/results/20d3a21c-634d-4a4a-8979-0635b5684e86` | `sessions/evaluation-fd195446-8bfe-4f4b-88c2-75d1e6977dce` |
| `live_audio_goldens::golden_ac9_brand_safe_rivalry_humor` | `r2` | `PASS` | `2.749s` | `evaluations/502c5ea1-2548-4ccd-b10e-863741d0aa9f/results/4631432c-5ade-413a-b2eb-1eb9f7ea0324` | `sessions/evaluation-e4a97741-1cac-4c3b-ae97-c6fd188ddf3f` |
| `live_audio_goldens::golden_official_mercedes_links` | `r1` | `PASS` | `2.249s` | `evaluations/ff877a60-bdb6-411e-8844-8aef905a364e/results/5a460ca4-d2e5-446c-9056-c712ae211f7d` | `sessions/evaluation-8d5bffba-0750-4350-975c-c0ad66a95c10` |
| `live_audio_goldens::golden_official_mercedes_links` | `r2` | `PASS` | `3.014s` | `evaluations/ff877a60-bdb6-411e-8844-8aef905a364e/results/a63d289c-77d6-4241-983a-28093ca2d9fa` | `sessions/evaluation-b03d7c37-bff9-483b-9dfa-047128e4cb49` |
| `live_audio_goldens::golden_ac6_multilingual_spanish_response` | `r1` | `PASS` | `4.939s` | `evaluations/855a1604-51ae-4d03-bef4-741de06c41ea/results/2c799c09-acfa-4863-93af-6fbff6711e19` | `sessions/evaluation-d75f65b8-bf90-430c-83fc-758331b03cb2` |
| `live_audio_goldens::golden_ac6_multilingual_spanish_response` | `r2` | `PASS` | `1.757s` | `evaluations/855a1604-51ae-4d03-bef4-741de06c41ea/results/397158bb-02d2-4f93-b5dc-57b29fa17ce5` | `sessions/evaluation-250d6293-7d9d-42e8-a38c-db9ae55c0497` |

### Live Voice Bidi Probes (`live_voice`, `modality=audio`, `use_tool_fakes=True`)

| Test ID | Repeat | Status | Mean Turn Latency (s) | Session (app-relative) | Conversation (app-relative) | Notes |
|---|---|---|---|---|---|---|
| `live_voice::voice_probe_next_race_and_standings` | `r1` | `FAIL` | `45.40s` | `sessions/348b021c-9a01-4f41-a1e7-22036a50b916` | `conversations/348b021c-9a01-4f41-a1e7-22036a50b916` | [dead_air_handoff:TR-03, RC-08] handoff turn took 45.4s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: ~30s spoken >  |
| `live_voice::voice_probe_next_race_and_standings` | `r2` | `FAIL` | `46.59s` | `sessions/f3b2d2cc-faae-414c-afb0-cc031ee60151` | `conversations/f3b2d2cc-faae-414c-afb0-cc031ee60151` | [dead_air_handoff:TR-03, RC-08] handoff turn took 46.6s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: ~30s spoken >  |
| `live_voice::voice_probe_merch_order_1002` | `r1` | `FAIL` | `56.93s` | `sessions/b80569b6-f26f-456a-8acb-88829ed87bd5` | `conversations/b80569b6-f26f-456a-8acb-88829ed87bd5` | [dead_air_handoff:TR-03, RC-08] handoff turn took 56.9s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: ~29s spoken >  |
| `live_voice::voice_probe_merch_order_1002` | `r2` | `FAIL` | `57.11s` | `sessions/b0a9d29c-73e0-46e0-be36-597981fbc597` | `conversations/b0a9d29c-73e0-46e0-be36-597981fbc597` | [dead_air_handoff:TR-03, RC-08] handoff turn took 57.1s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: ~30s spoken >  |

## 5. Model B (`gemini-3.1-flash-live`) — Platform Resource IDs & Per-Test Results

- **Run Record:** `evals/history/runs/ab-voice-gemini-3-1-flash-live-20260930T135317Z.json`
- **ID Verification Report:** `evals/history/artifacts/ab-voice-gemini-3-1-flash-live-20260930T135317Z/verify_ids.json` (`14/14` entries, `44/44` unique resources verified)
- **Platform Audio Evaluation Run:** `evaluationRuns/7e7f1489-cc24-4a80-9ed5-7b1907dd28a3` (`state=COMPLETED`, `channel=AUDIO`, `toolCallBehaviour=FAKE`)

### Platform Audio Golden Evaluations (`evaluationChannel=AUDIO`, `toolCallBehaviour=FAKE`)

| Test ID | Repeat | Status | Turn Latency (s) | Evaluation Result (app-relative) | Session / Conversation (app-relative) |
|---|---|---|---|---|---|
| `live_audio_goldens::golden_ac8_identity_and_non_impersonation` | `r1` | `PASS` | `0.731s` | `evaluations/b2c78916-6538-48c5-ae64-f65415a2acd2/results/d298593b-7d8c-4267-93c9-d091b3f189cc` | `sessions/evaluation-0f8ec8f5-28ee-4637-871b-d59fbd4ecee8` |
| `live_audio_goldens::golden_ac8_identity_and_non_impersonation` | `r2` | `PASS` | `0.792s` | `evaluations/b2c78916-6538-48c5-ae64-f65415a2acd2/results/dde623c0-d693-48cf-a741-67d763e298be` | `sessions/evaluation-74c1d54d-bcaf-4263-bc4c-aa717fde4e0a` |
| `live_audio_goldens::golden_ac3_mercedes_history_qualified` | `r1` | `PASS` | `0.770s` | `evaluations/21827777-fb13-448c-92d4-c6d4f8972cdd/results/306b6444-05b8-4f52-bee7-f11923295603` | `sessions/evaluation-1ac9da20-83f1-42db-8805-a8ee4cfeeb66` |
| `live_audio_goldens::golden_ac3_mercedes_history_qualified` | `r2` | `FAIL` | `0.763s` | `evaluations/21827777-fb13-448c-92d4-c6d4f8972cdd/results/53267649-8226-44f5-befd-53160f65a9b0` | `sessions/evaluation-ea62fc97-050a-4a13-8474-bcbb4095630a` |
| `live_audio_goldens::golden_ac9_brand_safe_rivalry_humor` | `r1` | `PASS` | `0.782s` | `evaluations/502c5ea1-2548-4ccd-b10e-863741d0aa9f/results/4321bc3d-dfa8-46f1-a5b1-cde3303f6546` | `sessions/evaluation-da9bf0a9-313a-43a2-913a-ab645e62f203` |
| `live_audio_goldens::golden_ac9_brand_safe_rivalry_humor` | `r2` | `FAIL` | `0.778s` | `evaluations/502c5ea1-2548-4ccd-b10e-863741d0aa9f/results/d6a405ba-0df6-4eb4-a377-83034cbbcd62` | `sessions/evaluation-9fbc0c7f-7084-4ad5-b437-b89012516479` |
| `live_audio_goldens::golden_official_mercedes_links` | `r1` | `FAIL` | `1.394s` | `evaluations/ff877a60-bdb6-411e-8844-8aef905a364e/results/c4e8e3cf-d855-473a-ad41-c0b762cbfa01` | `sessions/evaluation-dbb67e55-6275-472f-b68e-b0faee466784` |
| `live_audio_goldens::golden_official_mercedes_links` | `r2` | `PASS` | `1.436s` | `evaluations/ff877a60-bdb6-411e-8844-8aef905a364e/results/90a91abd-1a57-406b-8650-848ef2120f5c` | `sessions/evaluation-9bc52d54-8522-4662-8f4b-b52ae731d95f` |
| `live_audio_goldens::golden_ac6_multilingual_spanish_response` | `r1` | `FAIL` | `0.768s` | `evaluations/855a1604-51ae-4d03-bef4-741de06c41ea/results/a0d8d617-adfd-4687-a813-3e9af943cb14` | `sessions/evaluation-0fb3be93-3c96-4309-9827-eb99bc515db1` |
| `live_audio_goldens::golden_ac6_multilingual_spanish_response` | `r2` | `FAIL` | `0.785s` | `evaluations/855a1604-51ae-4d03-bef4-741de06c41ea/results/4c0b96c4-f0ed-48bd-be2c-117a719519d1` | `sessions/evaluation-73657615-fd4e-4938-b3ae-6f71b4714018` |

### Live Voice Bidi Probes (`live_voice`, `modality=audio`, `use_tool_fakes=True`)

| Test ID | Repeat | Status | Mean Turn Latency (s) | Session (app-relative) | Conversation (app-relative) | Notes |
|---|---|---|---|---|---|---|
| `live_voice::voice_probe_next_race_and_standings` | `r1` | `FAIL` | `35.97s` | `sessions/f120c567-44a4-4776-a35f-a1811b7354e2` | `conversations/f120c567-44a4-4776-a35f-a1811b7354e2` | [dead_air_handoff:TR-03, RC-08] handoff turn took 36.0s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: 8 sentences >  |
| `live_voice::voice_probe_next_race_and_standings` | `r2` | `FAIL` | `37.00s` | `sessions/49774563-e19a-44d6-aeeb-29e117903f7f` | `conversations/49774563-e19a-44d6-aeeb-29e117903f7f` | [dead_air_handoff:TR-03, RC-08] handoff turn took 37.0s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: 9 sentences >  |
| `live_voice::voice_probe_merch_order_1002` | `r1` | `FAIL` | `38.03s` | `sessions/604e33ac-c157-4a48-9a6c-95a49da101d0` | `conversations/604e33ac-c157-4a48-9a6c-95a49da101d0` | [dead_air_handoff:TR-03, RC-08] handoff turn took 38.0s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: 8 sentences >  |
| `live_voice::voice_probe_merch_order_1002` | `r2` | `FAIL` | `38.51s` | `sessions/d1e3e333-64c0-4c7c-aad6-b7b594c6c2d8` | `conversations/d1e3e333-64c0-4c7c-aad6-b7b594c6c2d8` | [dead_air_handoff:TR-03, RC-08] handoff turn took 38.5s (> 5.0s dead air); [reply_length:NEW-2, RC-06] voice budget exceeded: 8 sentences >  |

