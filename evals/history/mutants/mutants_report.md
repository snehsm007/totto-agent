# Totto CXAS Offline Suite — Mutation Testing Report

- **Generated at**: `2026-09-30T18:16:53Z`
- **Baseline (`cxas_app`)**: `217/217` passing across `tools, callbacks, config, lint` (`0` failed, `9.954s`)
- **Mutants Killed**: **`16/16` (`100.0%`)**

## Kill Rate by Category

| Category | Killed | Total | Kill Rate |
|---|---:|---:|---:|
| `callbacks` | 3 | 3 | 100.0% |
| `config` | 7 | 7 | 100.0% |
| `tools` | 6 | 6 | 100.0% |

## Mutant Matrix (`PASS -> FAIL` Verification)

| # | Mutant ID | Category | Taxonomy | Target File(s) | Status | Flipped (`PASS -> FAIL`) Scenarios |
|---:|---|---|---|---|---|---|
| 1 | `mutant_tr08_standings_both_alias` | `tools` | `TR-08` | `tools/get_driver_standings/python_function/python_code.py` | **KILLED** (1) | `tools::test_tools.py::test_get_driver_standings_mercedes_first_and_category_aliases[both]` |
| 2 | `mutant_tb03_unknown_race_fallback` | `tools` | `TB-3` | `tools/get_race_schedule/python_function/python_code.py` | **KILLED** (7) | `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Atlantis Grand Prix-payload]`, `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Atlantis Grand Prix-snapshot]`, `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Moon Grand Prix-payload]` (+4 more) |
| 3 | `mutant_tr10_broken_timezone_dst` | `tools` | `TR-10` | `tools/get_race_schedule/python_function/python_code.py` | **KILLED** (27) | `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[British Grand Prix-Silverstone-Sydney-Qualifying-2026-07-04T15:00-01:00-AEST-Sunday]`, `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[Mexico City Grand Prix-Mexico City-New York-Qualifying-2026-10-31T21:00-17:00-EDT-Saturday]`, `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[Mexico City Grand Prix-Mexico City-New York-Race-2026-11-01T20:00-15:00-EST-Sunday]` (+24 more) |
| 4 | `mutant_rc01_missing_merch_store_link` | `tools` | `RC-01` | `tools/get_official_links/python_function/python_code.py` | **KILLED** (12) | `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[None]`, `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[]`, `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[all]` (+9 more) |
| 5 | `mutant_tr09_missing_freshness_disclaimer` | `tools` | `TR-09`, `TB-1` | `tools/get_race_schedule/python_function/python_code.py` | **KILLED** (11) | `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-empty]`, `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-http429]`, `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-http500]` (+8 more) |
| 6 | `mutant_cb_order_id_regex` | `callbacks` | `TR-01`, `PRD-AC5` | `agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py` | **KILLED** (9) | `callbacks::scrapi::totto_root_agent::test_init_session_state_extracts_order_id_from_user_event`, `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[Bestellung 1002 ist nicht angekommen-1002]`, `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[Can you check order number 1001?-1001]` (+6 more) |
| 7 | `mutant_cb_sync_race_state_noop` | `callbacks` | `TR-10`, `PRD-AC7` | `agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py` | **KILLED** (2) | `callbacks::scrapi::race_info_agent::test_sync_race_state_persists_timezone_and_location`, `callbacks::test_state_callbacks.py::test_sync_race_state_persists_resolved_timezone` |
| 8 | `mutant_tr01_prompt_stuffed_example` | `config` | `TR-01` | `agents/merch_support_agent/instruction.txt` | **KILLED** (2) | `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`, `config::test_agent_instructions_and_contracts.py::test_no_test_prompts_hardcoded_in_instruction_examples` |
| 9 | `mutant_tr02_speak_phrase_in_tool_desc` | `config` | `TR-02`, `TR-03` | `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `global_instruction.txt` | **KILLED** (2) | `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`, `tools::test_tools.py::test_tool_obeys_cxas_static_contracts_and_no_code_leak_phrases[get_race_schedule]` |
| 10 | `mutant_rc02_toto_impersonation_and_drop` | `config` | `RC-02`, `RC-10`, `TR-04` | `agents/totto_root_agent/instruction.txt`, `agents/merch_support_agent/instruction.txt`, `global_instruction.txt` | **KILLED** (6) | `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`, `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`, `config::test_agent_instructions_and_contracts.py::test_instruction_files_are_plain_prose_without_markdown_or_raw_urls` (+3 more) |
| 11 | `mutant_rc11_invalid_app_schema` | `config` | `RC-11` | `app.json`, `agents/totto_root_agent/instruction.txt` | **KILLED** (3) | `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`, `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`, `lint::cxas_lint` |
| 12 | `mutant_bundle_persona_drift` | `config` | `F9` | `agents/race_info_agent/instruction.txt` | **KILLED** (2) | `config::test_agent_instructions_and_contracts.py::test_instruction_files_are_plain_prose_without_markdown_or_raw_urls`, `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib` |
| 13 | `mutant_bundle_openf1_helper_drift` | `tools` | `F9`, `TB-1` | `tools/get_driver_standings/python_function/python_code.py` | **KILLED** (3) | `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib`, `tools::test_openf1_faults.py::test_worst_case_latency_with_hanging_openf1_stays_within_voice_budget[standings-hang]`, `tools::test_openf1_faults.py::test_worst_case_latency_with_hanging_openf1_stays_within_voice_budget[standings-slow]` |
| 14 | `mutant_voice_guidelines_dropped` | `config` | `F10`, `RC-06`, `RC-07`, `NEW-2` | `global_instruction.txt` | **KILLED** (1) | `config::test_agent_instructions_and_contracts.py::test_global_voice_guidelines_cover_urls_length_and_spoken_numbers` |
| 15 | `mutant_voice_sanitizer_noop` | `callbacks` | `F10`, `RC-06`, `RC-07` | `agents/merch_support_agent/after_model_callbacks/voice_sanitizer/python_code.py` | **KILLED** (3) | `callbacks::test_voice_sanitizer.py::test_markdown_emoji_and_url_prefixes_are_removed_but_content_is_kept[merch_support_agent]`, `callbacks::test_voice_sanitizer.py::test_tool_calls_are_kept_in_order_and_untouched[merch_support_agent]`, `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib` |
| 16 | `mutant_repetitive_boilerplate_mantra` | `config` | `NEW-2`, `RC-06` | `agents/race_info_agent/instruction.txt` | **KILLED** (1) | `config::test_agent_instructions_and_contracts.py::test_instructions_forbid_repetitive_boilerplate_and_examples_pass_grader` |

## Detailed Mutant Breakdown

### 1. `mutant_tr08_standings_both_alias` (TOOLS — TR-08)
- **Description**: Remove 'both' -> 'all' category alias from get_driver_standings so category='both' raises an invalid category error.
- **Target Files**: `tools/get_driver_standings/python_function/python_code.py`
- **Layers Checked**: `tools` (`2.193s`)
- **Result**: **KILLED** (`1` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `tools::test_tools.py::test_get_driver_standings_mercedes_first_and_category_aliases[both]`

### 2. `mutant_tb03_unknown_race_fallback` (TOOLS — TB-3)
- **Description**: Fall back to meetings[0] (Australian GP) when _select_meeting receives an unknown race query instead of returning None/UNKNOWN_RACE.
- **Target Files**: `tools/get_race_schedule/python_function/python_code.py`
- **Layers Checked**: `tools` (`2.053s`)
- **Result**: **KILLED** (`7` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Atlantis Grand Prix-payload]`
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Atlantis Grand Prix-snapshot]`
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Moon Grand Prix-payload]`
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Moon Grand Prix-snapshot]`
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Portuguese Grand Prix-payload]`
  - `tools::test_race_schedule_defects.py::test_unknown_race_returns_error_without_race_data[Portuguese Grand Prix-snapshot]`
  - `tools::test_tools.py::test_get_race_schedule_empty_and_unknown_query_error`

### 3. `mutant_tr10_broken_timezone_dst` (TOOLS — TR-10)
- **Description**: Bypass dt_utc.astimezone(tz_obj) in get_race_schedule so local_start stays in UTC across DST and timezone conversions.
- **Target Files**: `tools/get_race_schedule/python_function/python_code.py`
- **Layers Checked**: `tools` (`2.396s`)
- **Result**: **KILLED** (`27` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[British Grand Prix-Silverstone-Sydney-Qualifying-2026-07-04T15:00-01:00-AEST-Sunday]`
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[Mexico City Grand Prix-Mexico City-New York-Qualifying-2026-10-31T21:00-17:00-EDT-Saturday]`
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[Mexico City Grand Prix-Mexico City-New York-Race-2026-11-01T20:00-15:00-EST-Sunday]`
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[Singapore Grand Prix-Marina Bay-Sydney-Race-2026-10-11T12:00-23:00-AEDT-Sunday]`
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[United States Grand Prix-Austin-London-Qualifying-2026-10-24T21:00-22:00-BST-Saturday]`
  - `tools::test_timezones_dst.py::test_local_times_follow_dst_boundaries[United States Grand Prix-Austin-London-Race-2026-10-25T20:00-20:00-GMT-Sunday]`
  - `tools::test_timezones_dst.py::test_more_unseen_cities_resolve_via_zoneinfo[Honolulu-Pacific/Honolulu-03:00]`
  - `tools::test_timezones_dst.py::test_more_unseen_cities_resolve_via_zoneinfo[Kathmandu-Asia/Kathmandu-18:45]`
  - `tools::test_timezones_dst.py::test_more_unseen_cities_resolve_via_zoneinfo[Nairobi-Africa/Nairobi-16:00]`
  - `tools::test_timezones_dst.py::test_sydney_times_across_2026_10_03_04_dst_start_on_kuala_lumpur_weekend[Qualifying-18:00-AEST-Saturday]`
  - `tools::test_timezones_dst.py::test_sydney_times_across_2026_10_03_04_dst_start_on_kuala_lumpur_weekend[Race-18:00-AEDT-Sunday]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[America/New_York-09:00 EDT (New York)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Australia/Sydney-00:00 AEDT (Sydney)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Berlin, Germany-15:00 CEST (Berlin)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[EST-09:00 EDT (New York)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Europe/London-14:00 BST (London)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[I'm watching from New York, Eastern Time-09:00 EDT (New York)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[JST-22:00 JST (Tokyo)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Sydney, Australia-00:00 AEDT (Sydney)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Sydney-00:00 AEDT (Sydney)-False]`
  - `tools::test_tools.py::test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion[Tokyo, Japan-22:00 JST (Tokyo)-False]`
  - `tools::test_tools.py::test_get_race_schedule_specific_2026_races_and_seasonal_dst[British Grand Prix-Sydney, Australia-British Grand Prix]`
  - `tools::test_tools.py::test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo[Auckland-Pacific/Auckland-NZDT (Auckland)]`
  - `tools::test_tools.py::test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo[Mumbai-Asia/Kolkata-IST (Mumbai)]`
  - `tools::test_tools.py::test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo[S\xe3o Paulo-America/Sao_Paulo-BRT (Sao Paulo)]`
  - `tools::test_tools.py::test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo[Toronto-America/Toronto-EDT (Toronto)]`
  - `tools::test_tools.py::test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo[Vienna-Europe/Vienna-CEST (Vienna)]`

### 4. `mutant_rc01_missing_merch_store_link` (TOOLS — RC-01)
- **Description**: Replace official https://shop.mercedesamgf1.com URL with broken URL and remove 'store'/'shop' aliases in get_official_links.
- **Target Files**: `tools/get_official_links/python_function/python_code.py`
- **Layers Checked**: `tools` (`1.982s`)
- **Result**: **KILLED** (`12` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[None]`
  - `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[]`
  - `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[all]`
  - `tools::test_merch_and_links.py::test_all_links_include_every_official_destination_and_non_transactional_notice[both]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[SHOP]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[Store ]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[merch]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[merchandise]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[shop]`
  - `tools::test_merch_and_links.py::test_merch_store_aliases_return_official_store[store]`
  - `tools::test_tools.py::test_get_official_links_valid_categories[merch-https://shop.mercedesamgf1.com]`
  - `tools::test_tools.py::test_get_official_links_valid_categories[store-https://shop.mercedesamgf1.com]`

### 5. `mutant_tr09_missing_freshness_disclaimer` (TOOLS — TR-09, TB-1)
- **Description**: Remove freshness_disclaimer text and overwrite data_source provenance in get_race_schedule responses.
- **Target Files**: `tools/get_race_schedule/python_function/python_code.py`
- **Layers Checked**: `tools` (`1.993s`)
- **Result**: **KILLED** (`11` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-empty]`
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-http429]`
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-http500]`
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-malformed]`
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-non_list]`
  - `tools::test_openf1_faults.py::test_openf1_fault_falls_back_to_labelled_snapshot[schedule_next-timeout]`
  - `tools::test_openf1_faults.py::test_partial_openf1_failure_never_mixes_live_label_with_fallback[schedule_next-faults0]`
  - `tools::test_openf1_faults.py::test_partial_openf1_failure_never_mixes_live_label_with_fallback[schedule_next-faults1]`
  - `tools::test_race_schedule_defects.py::test_live_label_only_when_openf1_payload_was_served[get_race_schedule-kwargs0]`
  - `tools::test_race_schedule_defects.py::test_snapshot_data_is_labelled_snapshot_with_freshness_disclaimer[get_race_schedule-kwargs0]`
  - `tools::test_tools.py::test_get_race_schedule_without_timezone_asks_before_local_times`

### 6. `mutant_cb_order_id_regex` (CALLBACKS — TR-01, PRD-AC5)
- **Description**: Break ORDER_ID_PATTERN regex in init_session_state so order IDs (ORD-xxxx, 1001-1005) are never extracted into session state.
- **Target Files**: `agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py`
- **Layers Checked**: `callbacks` (`1.543s`)
- **Result**: **KILLED** (`9` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `callbacks::scrapi::totto_root_agent::test_init_session_state_extracts_order_id_from_user_event`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[Bestellung 1002 ist nicht angekommen-1002]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[Can you check order number 1001?-1001]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[Meine Bestellnummer ist 1003-1003]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[O\xf9 en est ma commande 1003 ?-1003]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[\xbfD\xf3nde est\xe1 mi pedido #1001?-1001]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_extracts_order_id_from_multilingual_phrases[\xbfD\xf3nde est\xe1 mi pedido n\xfamero 1002?-1002]`
  - `callbacks::test_state_callbacks.py::test_init_session_state_keeps_known_order_and_updates_on_new_one`
  - `callbacks::test_state_callbacks.py::test_init_session_state_preserves_existing_session_parameters_and_extracts_order_id`

### 7. `mutant_cb_sync_race_state_noop` (CALLBACKS — TR-10, PRD-AC7)
- **Description**: Short-circuit sync_race_state after_tool_callback to return None without persisting resolved user_timezone or last_queried_race.
- **Target Files**: `agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py`
- **Layers Checked**: `callbacks` (`1.532s`)
- **Result**: **KILLED** (`2` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `callbacks::scrapi::race_info_agent::test_sync_race_state_persists_timezone_and_location`
  - `callbacks::test_state_callbacks.py::test_sync_race_state_persists_resolved_timezone`

### 8. `mutant_tr01_prompt_stuffed_example` (CONFIG — TR-01)
- **Description**: Inject hardcoded tracking number DHL-9928174 and literal eval probe user prompt into merch_support_agent <examples>.
- **Target Files**: `agents/merch_support_agent/instruction.txt`
- **Layers Checked**: `config` (`0.811s`)
- **Result**: **KILLED** (`2` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`
  - `config::test_agent_instructions_and_contracts.py::test_no_test_prompts_hardcoded_in_instruction_examples`

### 9. `mutant_tr02_speak_phrase_in_tool_desc` (CONFIG — TR-02, TR-03)
- **Description**: Add 'Speak a conversational pacing phrase before calling' to get_race_schedule description/docstring and drop Zero Raw Code rule.
- **Target Files**: `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `global_instruction.txt`
- **Layers Checked**: `config`, `tools` (`2.735s`)
- **Result**: **KILLED** (`2` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`
  - `tools::test_tools.py::test_tool_obeys_cxas_static_contracts_and_no_code_leak_phrases[get_race_schedule]`

### 10. `mutant_rc02_toto_impersonation_and_drop` (CONFIG — RC-02, RC-10, TR-04)
- **Description**: Overlay iteration_3 instruction regression (dropping Toto Wolff non-impersonation, live human escalation, and mock order disclosure) and remove Multilingual Continuity.
- **Target Files**: `agents/totto_root_agent/instruction.txt`, `agents/merch_support_agent/instruction.txt`, `global_instruction.txt`
- **Layers Checked**: `config` (`0.812s`)
- **Result**: **KILLED** (`6` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`
  - `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`
  - `config::test_agent_instructions_and_contracts.py::test_instruction_files_are_plain_prose_without_markdown_or_raw_urls`
  - `config::test_agent_instructions_and_contracts.py::test_instruction_mock_freshness_and_conciseness_rules`
  - `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib`
  - `config::test_agent_instructions_and_contracts.py::test_unsupported_language_policy_configured`

### 11. `mutant_rc11_invalid_app_schema` (CONFIG — RC-11)
- **Description**: Add unknownInvalidSchemaField and broken rootAgent to app.json and reference nonexistent_ghost_tool in totto_root_agent instruction.
- **Target Files**: `app.json`, `agents/totto_root_agent/instruction.txt`
- **Layers Checked**: `lint`, `config` (`4.016s`)
- **Result**: **KILLED** (`3` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps`
  - `config::test_agent_instructions_and_contracts.py::test_app_json_and_global_instruction_configuration`
  - `lint::cxas_lint`

### 12. `mutant_bundle_persona_drift` (CONFIG — F9)
- **Description**: Hand-edit race_info_agent's bundled <persona> copy (bold driver names + #63/#12) so it drifts from lib/shared_prompts/persona.txt.
- **Target Files**: `agents/race_info_agent/instruction.txt`
- **Layers Checked**: `config` (`0.833s`)
- **Result**: **KILLED** (`2` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_instruction_files_are_plain_prose_without_markdown_or_raw_urls`
  - `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib`

### 13. `mutant_bundle_openf1_helper_drift` (TOOLS — F9, TB-1)
- **Description**: Change the bundled OpenF1 HTTP helper timeout (2s -> 30s) in get_driver_standings only, so the copy drifts from lib/shared_python/openf1_http.py.
- **Target Files**: `tools/get_driver_standings/python_function/python_code.py`
- **Layers Checked**: `config`, `tools` (`3.021s`)
- **Result**: **KILLED** (`3` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib`
  - `tools::test_openf1_faults.py::test_worst_case_latency_with_hanging_openf1_stays_within_voice_budget[standings-hang]`
  - `tools::test_openf1_faults.py::test_worst_case_latency_with_hanging_openf1_stays_within_voice_budget[standings-slow]`

### 14. `mutant_voice_guidelines_dropped` (CONFIG — F10, RC-06, RC-07, NEW-2)
- **Description**: Delete the shared voice <guidelines> block (plain text, no raw URLs, 2-3 sentence budget, spoken numbers) from global_instruction.txt.
- **Target Files**: `global_instruction.txt`
- **Layers Checked**: `config` (`0.907s`)
- **Result**: **KILLED** (`1` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_global_voice_guidelines_cover_urls_length_and_spoken_numbers`

### 15. `mutant_voice_sanitizer_noop` (CALLBACKS — F10, RC-06, RC-07)
- **Description**: Make merch_support_agent's voice_sanitizer after_model_callback return None before cleaning, so markdown/emoji/https:// reach TTS.
- **Target Files**: `agents/merch_support_agent/after_model_callbacks/voice_sanitizer/python_code.py`
- **Layers Checked**: `callbacks`, `config` (`2.367s`)
- **Result**: **KILLED** (`3` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `callbacks::test_voice_sanitizer.py::test_markdown_emoji_and_url_prefixes_are_removed_but_content_is_kept[merch_support_agent]`
  - `callbacks::test_voice_sanitizer.py::test_tool_calls_are_kept_in_order_and_untouched[merch_support_agent]`
  - `config::test_agent_instructions_and_contracts.py::test_shared_regions_in_sync_with_lib`

### 16. `mutant_repetitive_boilerplate_mantra` (CONFIG — NEW-2, RC-06)
- **Description**: Re-introduce repetitive 'According to the latest-available 2026 data' and self-introduction across consecutive turns in race_info_agent <examples>.
- **Target Files**: `agents/race_info_agent/instruction.txt`
- **Layers Checked**: `config` (`0.846s`)
- **Result**: **KILLED** (`1` scenarios flipped `PASS -> FAIL`)
- **Scenarios Flipped `PASS -> FAIL`**:
  - `config::test_agent_instructions_and_contracts.py::test_instructions_forbid_repetitive_boilerplate_and_examples_pass_grader`
