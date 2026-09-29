# Live CXAS App Before/After Identity Proof (`before_after_diff.md`)

- **App Resource**: `projects/your-gcp-project/locations/us/apps/00000000-0000-0000-0000-000000000000`
- **Before Snapshot (`live_before`)**: `evals/history/snapshots/20260928T215748Z_live_before` (run `20260928T215748Z_snapshot_fa27a68`, captured `2026-09-28T21:57:48Z`, version `b11332a0-b304-41e1-baac-57cd0ced05da` / `r3-live_before-20260928T215748Z`)
- **After Snapshot (`live_after`)**: `evals/history/snapshots/20260929T010751Z_live_after` (run `20260929T010751Z_snapshot_7147f2d`, captured `2026-09-29T01:07:51Z`, version `40170087-a913-495f-b3fb-644dbfdbebd7` / `r3-live_after-20260929T010751Z`)
- **Overall Verdict**: **`ALL_CHECKS_PASSED = True`** — Zero modifications to live agents, instructions, tools, callbacks, guardrails, or model settings.

---

## 1. App-Level Metadata & Settings Identity

| Property | `live_before` (`20260928T215748Z`) | `live_after` (`20260929T010751Z`) | Match |
|---|---|---|:---:|
| `update_time` | `2026-09-28T20:55:38.643615Z` | `2026-09-28T20:55:38.643615Z` | `True` |
| `etag` | `8IMUQCFzmitwcdweGE5ZENgx0SNE6YWMRqUbvW/6TXc=` | `8IMUQCFzmitwcdweGE5ZENgx0SNE6YWMRqUbvW/6TXc=` | `True` |
| `model_settings` | `{"model": "gemini-3.0-flash-001"}` | `{"model": "gemini-3.0-flash-001"}` | `True` |
| `guardrails` | `[]` | `[]` | `True` |
| `root_agent` | `projects/your-gcp-project/locations/us/apps/00000000-0000-0000-0000-000000000000/agents/c1111111-2222-3333-4444-555555555551` | `projects/your-gcp-project/locations/us/apps/00000000-0000-0000-0000-000000000000/agents/c1111111-2222-3333-4444-555555555551` | `True` |
| `variable_declarations` (count) | `4` (`user_timezone`, `user_location`, `order_id`, `is_mock_mode`) | `4` (`user_timezone`, `user_location`, `order_id`, `is_mock_mode`) | `True` |
| `core_normalized_tree_hash` | `3dc6b1f0ea01a07eacafb1fa61c53c72ed7d90a61ac2e3ac5d50beb799c452d0` | `3dc6b1f0ea01a07eacafb1fa61c53c72ed7d90a61ac2e3ac5d50beb799c452d0` | `True` |
| `core_raw_tree_hash` | `e0fc9e06d5b04ef9b0f708baac6ad5a9d1b5de29ac4e09b37aae987672266ece` | `e0fc9e06d5b04ef9b0f708baac6ad5a9d1b5de29ac4e09b37aae987672266ece` | `True` |

---

## 2. File-by-File Cryptographic Comparison of Exported Agent/Tool/Callback/Instruction Files (22/22 Byte-Identical)

| Relative Path in Exported `cxas_app/` | Size (Bytes) | SHA-256 (`live_before`) | SHA-256 (`live_after`) | Raw Identical | Normalized Identical |
|---|---:|---|---|:---:|:---:|
| `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py` | 606 | `525205cec7dda3a37e5b8d273ac9591be7e1489267e11a4cf9ff395c01fd7cdb` | `525205cec7dda3a37e5b8d273ac9591be7e1489267e11a4cf9ff395c01fd7cdb` | `True` | `True` |
| `agents/merch_support_agent/instruction.txt` | 6278 | `c8cd0c16ccd81229b8683780cfce93039a1fbb5198b2b124b2ad67e6c4fbf6da` | `c8cd0c16ccd81229b8683780cfce93039a1fbb5198b2b124b2ad67e6c4fbf6da` | `True` | `True` |
| `agents/merch_support_agent/merch_support_agent.json` | 674 | `ccda6abfac5694f67ae40cd7d8b8e310d4d695cbb6f06b2837fdc54f5f853acc` | `ccda6abfac5694f67ae40cd7d8b8e310d4d695cbb6f06b2837fdc54f5f853acc` | `True` | `True` |
| `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py` | 745 | `6f411600faf8c0ee6ae40ae279fad6692e84e32e5ed5e32c6059d8c2cc52de59` | `6f411600faf8c0ee6ae40ae279fad6692e84e32e5ed5e32c6059d8c2cc52de59` | `True` | `True` |
| `agents/race_info_agent/instruction.txt` | 7699 | `5f792ce070f0156b22c9a9f7df361106ff44d2fcd26ce4aaf6cb406b5d74b9f0` | `5f792ce070f0156b22c9a9f7df361106ff44d2fcd26ce4aaf6cb406b5d74b9f0` | `True` | `True` |
| `agents/race_info_agent/race_info_agent.json` | 691 | `16b10e2d2528dca0000401c654fc9312f2ed485b80beeeb18f868237184c9e93` | `16b10e2d2528dca0000401c654fc9312f2ed485b80beeeb18f868237184c9e93` | `True` | `True` |
| `agents/ticketing_agent/instruction.txt` | 4474 | `cdae9a2cc3a2e6c7116a7beac02db6605fa484b5435ca01718d96c3bdf0ba6d2` | `cdae9a2cc3a2e6c7116a7beac02db6605fa484b5435ca01718d96c3bdf0ba6d2` | `True` | `True` |
| `agents/ticketing_agent/ticketing_agent.json` | 382 | `716b7a161889359d70570adeb4a93be806d3fc0e8fc788b17fbf1398a2d07413` | `716b7a161889359d70570adeb4a93be806d3fc0e8fc788b17fbf1398a2d07413` | `True` | `True` |
| `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py` | 1041 | `5f1e60670573ede68f64d2896ea68cf1ef8c49234717355d35eb7cc8581f07de` | `5f1e60670573ede68f64d2896ea68cf1ef8c49234717355d35eb7cc8581f07de` | `True` | `True` |
| `agents/totto_root_agent/instruction.txt` | 9175 | `d6a815b2416de9ff60f7f1f8c88bede5785c22f139a36fab281ac0708777be6f` | `d6a815b2416de9ff60f7f1f8c88bede5785c22f139a36fab281ac0708777be6f` | `True` | `True` |
| `agents/totto_root_agent/totto_root_agent.json` | 784 | `86de1915ab255c7baf4886108c0061f489781663e7c248ccff6630eefbb32602` | `86de1915ab255c7baf4886108c0061f489781663e7c248ccff6630eefbb32602` | `True` | `True` |
| `app.json` | 1170 | `ac90ccf17f91b79e6bbdf2f4e67ff1d9f90d76dfbc2c1d012571335a86737fab` | `ac90ccf17f91b79e6bbdf2f4e67ff1d9f90d76dfbc2c1d012571335a86737fab` | `True` | `True` |
| `global_instruction.txt` | 4820 | `e701887569230d7249daf1166035eed25fc506fa235cf8b3db65652834f06b3b` | `e701887569230d7249daf1166035eed25fc506fa235cf8b3db65652834f06b3b` | `True` | `True` |
| `pythonEnvFiles/pythonEnvFiles.json` | 3 | `8eb95bcbc154530931e15fc418c8b1fe991095671409552099ea1aa596999ede` | `8eb95bcbc154530931e15fc418c8b1fe991095671409552099ea1aa596999ede` | `True` | `True` |
| `tools/get_driver_standings/get_driver_standings.json` | 716 | `8329afb6b4e99d1013a6df6e9be94f3e432f39c2be720ba731cea5a03a91eaef` | `8329afb6b4e99d1013a6df6e9be94f3e432f39c2be720ba731cea5a03a91eaef` | `True` | `True` |
| `tools/get_driver_standings/python_function/python_code.py` | 14032 | `2b8ba15a519737a56313755acee7b17eabdeb925a00f18f77bc5682adffef619` | `2b8ba15a519737a56313755acee7b17eabdeb925a00f18f77bc5682adffef619` | `True` | `True` |
| `tools/get_official_links/get_official_links.json` | 595 | `051befb2e629295b8c81153134667ce854b80b38f5a923774a30f24bf0de9ddd` | `051befb2e629295b8c81153134667ce854b80b38f5a923774a30f24bf0de9ddd` | `True` | `True` |
| `tools/get_official_links/python_function/python_code.py` | 3100 | `f6d0faa1ff758ddec594013058ef7e21e69ee1eb5ea71c80f985708b5e4d8ea4` | `f6d0faa1ff758ddec594013058ef7e21e69ee1eb5ea71c80f985708b5e4d8ea4` | `True` | `True` |
| `tools/get_race_schedule/get_race_schedule.json` | 765 | `a6a40fb6acb93a35996b4fe6449acf26401eb927736fa7626b061827e50c3d56` | `a6a40fb6acb93a35996b4fe6449acf26401eb927736fa7626b061827e50c3d56` | `True` | `True` |
| `tools/get_race_schedule/python_function/python_code.py` | 40240 | `b9bbd880c44cdf5f9ae856c14eb5022b2ba85a0d0f25663d4c70c903634c094d` | `b9bbd880c44cdf5f9ae856c14eb5022b2ba85a0d0f25663d4c70c903634c094d` | `True` | `True` |
| `tools/lookup_mock_merch_order/lookup_mock_merch_order.json` | 610 | `7317e1732c4990f2b4ad667a3d472e0bfe3e4784ec46b4d8425bfd93817dc9c0` | `7317e1732c4990f2b4ad667a3d472e0bfe3e4784ec46b4d8425bfd93817dc9c0` | `True` | `True` |
| `tools/lookup_mock_merch_order/python_function/python_code.py` | 4739 | `19538763f206c0c53d87c661564c22ca2defd1fe6eb8a8d5ae94f7190e5b4882` | `19538763f206c0c53d87c661564c22ca2defd1fe6eb8a8d5ae94f7190e5b4882` | `True` | `True` |

---

## 3. Expected, Allowed Evaluation & Snapshot Additions on the Platform

Per R5 (`ORIGINAL_REQUEST.md`), our suite never pushed or modified any agent, tool, callback, instruction, guardrail, or model setting on the live app, and never deleted any pre-existing versions or datasets. The only additions between `live_before` and `live_after` are:

1. **Immutable Version Snapshots Created by `totto_suite snapshot`**:
   - `b11332a0-b304-41e1-baac-57cd0ced05da` (`r3-live_before-20260928T215748Z`, created `2026-09-28T21:58:11.292847Z`)
   - `40170087-a913-495f-b3fb-644dbfdbebd7` (`r3-live_after-20260929T010751Z`, created `2026-09-29T01:08:21.248655Z`)
   - All 3 pre-existing versions (`8523ee41-e211-4f32-901d-34b1b56792f0`, `8f80d3eb-8290-419a-94d7-ceff64b804c1`, `b755f68b-c8fc-4f29-864c-ce85745c626c`) remain intact in `list_versions`.
2. **Team-Prefixed (`r4-totto-*`) Golden Evaluations & Evaluation Expectations** (14 files included in the exported bundle):
   - `evaluationExpectations/eval_exp_37741d4a/eval_exp_37741d4a.json` (`206` bytes, SHA-256 `1c2a1d862366b9b447ea1415258ea0af1ea3c72b379b73f35624432da4cabaac`)
   - `evaluationExpectations/eval_exp_4beeec7e/eval_exp_4beeec7e.json` (`233` bytes, SHA-256 `59f88dfa9a0d52bffff508ec8036d17109958a19faf16114ace7cb70b44c5a48`)
   - `evaluationExpectations/eval_exp_51903402/eval_exp_51903402.json` (`248` bytes, SHA-256 `ec9935183e36794df744774fa95e1bdef3ca7020c483e8ae299feaa6ca8f2e8c`)
   - `evaluationExpectations/eval_exp_579dc645/eval_exp_579dc645.json` (`250` bytes, SHA-256 `8e1285570d95464d3383ab7180cb6b74ffe1d0181dd0e6fced57723545c1f5bc`)
   - `evaluationExpectations/eval_exp_65647573/eval_exp_65647573.json` (`204` bytes, SHA-256 `95bdde36c05c628e86f5223946caa2371d5bebcd30ebc2ed80e074698ad38e99`)
   - `evaluationExpectations/eval_exp_9d099b07/eval_exp_9d099b07.json` (`203` bytes, SHA-256 `23eef6a8405e91d3a108c8c1c4bdb539d4ddbd0634781ff5c2dc2c7621dea9b2`)
   - `evaluationExpectations/eval_exp_cce34788/eval_exp_cce34788.json` (`209` bytes, SHA-256 `89df78db60f6e6169cac0d669936c60bc61039e7095fce5c83cbfd479b678589`)
   - `evaluationExpectations/eval_exp_e811eddd/eval_exp_e811eddd.json` (`179` bytes, SHA-256 `79520b2501c0ae9ba40bc6a3cce9d5fdb4b6a297d7de19f2d1bbdce11e4331ee`)
   - `evaluationExpectations/eval_exp_f3522ff9/eval_exp_f3522ff9.json` (`200` bytes, SHA-256 `f029e545b2a1a0c47a19c7136180fcbc105749f3de390a565b1a6ba341ef8449`)
   - `evaluations/r4-totto-golden_ac3_mercedes_history_qualified/r4-totto-golden_ac3_mercedes_history_qualified.json` (`1139` bytes, SHA-256 `6eae8f447e1f835b83b05d453f1acc996eaf94e0e3380ddf7bb36cfeec416356`)
   - `evaluations/r4-totto-golden_ac6_multilingual_spanish_response/r4-totto-golden_ac6_multilingual_spanish_response.json` (`1018` bytes, SHA-256 `3a8101f5a99c85bb2b4a47109bc7d4b5714a4c999f486ae4d2d3d8cb78a294c7`)
   - `evaluations/r4-totto-golden_ac8_identity_and_non_impersonation/r4-totto-golden_ac8_identity_and_non_impersonation.json` (`1116` bytes, SHA-256 `3c8f28b6af4f7073809f769e183078780da1158d752b3c31f0bf662426c4d2b4`)
   - `evaluations/r4-totto-golden_ac9_brand_safe_rivalry_humor/r4-totto-golden_ac9_brand_safe_rivalry_humor.json` (`1099` bytes, SHA-256 `14bf5c2bd57447f5aab61745a90773d02d534720fd741e96743620a034a68b46`)
   - `evaluations/r4-totto-golden_official_mercedes_links/r4-totto-golden_official_mercedes_links.json` (`1433` bytes, SHA-256 `59d99a849d36d1cbb5e2ab182240c651b427558c31427879f26b2e17c8dccbf7`)
3. **Evaluation Runs & Conversation Logs Created by Live Suite Run `20260929T001319Z_live_fd9be8b`**:
   - Evaluation runs: `0` -> `15` (`+15` runs across 5 golden evaluations × 3 repeats)
   - Conversations (24h window by source): `{"LIVE": 191, "SIMULATOR": 3, "EVAL": 36, "AGENT_TOOL": 0}` -> `{"LIVE": 264, "SIMULATOR": 3, "EVAL": 51, "AGENT_TOOL": 0}`
