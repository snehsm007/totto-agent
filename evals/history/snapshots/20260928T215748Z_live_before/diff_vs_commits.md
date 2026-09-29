# Live export vs repo commits (normalized)

Export: `evals/history/snapshots/20260928T215748Z_live_before/cxas_app` (normalized tree hash `3dc6b1f0ea01a07eacafb1fa61c53c72ed7d90a61ac2e3ac5d50beb799c452d0`).
Nearest source commit: `b48bd74`; identical commits: `b48bd74`, `f073e02`.

Normalization rules (applied to both sides; the raw file-level view is listed per commit so nothing is hidden):

- N0 skip __pycache__/, *.pyc and local-only config files gecx-config.json, environment.json
- N1 callback code files are renamed to the server layout agents/<agent>/<callback_kind>/<callback_kind>_<NN>/python_code.py (NN = 1-based position in the agent JSON list) and the JSON pythonCode paths rewritten; list order is preserved
- N2 tool pythonFunction.description is set to the docstring of the function in the tool's python code (the server derives it on import)
- N3 set-valued lists sorted: tools, childAgents, toolsets, guardrails; variableDeclarations sorted by name
- N4 empty values ([], {}, "", null) dropped (proto3 JSON omits them)
- N5 app.json platform-managed keys removed and reported separately: loggingSettings
- N6 JSON files that are empty after N4 are dropped (e.g. pythonEnvFiles/pythonEnvFiles.json = {})
- N7 JSON re-serialized with sorted keys and 2-space indent; text files use LF line endings and exactly one trailing newline

Platform-managed app.json keys found in the live export (excluded by N5): `{"loggingSettings": {"conversationLoggingSettings": {"retentionWindow": "31536000s"}}}`

| commit | time | identical (normalized) | differing | only in commit | only in live | raw differing / only-commit / only-live |
|---|---|---|---|---|---|---|
| `b48bd74` | 2026-09-28T21:57:38Z | yes | 0 | 0 | 0 | 9 / 3 / 4 |
| `f073e02` | 2026-09-28T20:55:59Z | yes | 0 | 0 | 0 | 9 / 3 / 4 |
| `a7c3094` | 2026-09-28T17:24:28Z | no | 17 | 0 | 4 | 17 / 0 / 5 |
| `1a17988` | 2026-09-28T17:21:42Z | no | 17 | 0 | 4 | 17 / 0 / 5 |
| `bdb8f3b` | 2026-09-28T17:14:30Z | no | 17 | 0 | 4 | 17 / 0 / 5 |

## `b48bd74` totto_suite: M1 core (config, records, gitinfo, cxasapi read/export/version, taxonomy, layer discovery, CLI offline/snapshot/trend, trend view)

Identical after normalization.
Raw (un-normalized) view: differing `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_official_links/get_official_links.json`, `tools/get_race_schedule/get_race_schedule.json`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`; only in commit `agents/merch_support_agent/after_tool_callbacks/sync_order_state/python_code.py`, `agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py`; only in live `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `pythonEnvFiles/pythonEnvFiles.json`

Raw differences absorbed by the normalization rules (JSON pretty-printed with sorted keys, nothing else changed):

```diff
--- commit:b48bd74/cxas_app/agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py
+++ live-export/cxas_app/agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py
@@ -0,0 +1,20 @@
+from typing import Any, Optional
+
+
+def after_tool_callback(
+    tool: Tool,
+    input: dict[str, Any],
+    callback_context: CallbackContext,
+    tool_response: dict[str, Any],
+) -> Optional[dict[str, Any]]:
+    """Persists looked-up order_id and mock mode flag into session state after lookup_mock_merch_order."""
+    state = callback_context.state
+    state["is_mock_mode"] = True
+    resolved_order = (
+        str(tool_response.get("order_id") or input.get("order_id") or "")
+        .strip()
+        .lstrip("#")
+    )
+    if resolved_order:
+        state["order_id"] = resolved_order
+    return None
--- commit:b48bd74/cxas_app/agents/merch_support_agent/after_tool_callbacks/sync_order_state/python_code.py
+++ live-export/cxas_app/agents/merch_support_agent/after_tool_callbacks/sync_order_state/python_code.py
@@ -1,20 +0,0 @@
-from typing import Any, Optional
-
-
-def after_tool_callback(
-    tool: Tool,
-    input: dict[str, Any],
-    callback_context: CallbackContext,
-    tool_response: dict[str, Any],
-) -> Optional[dict[str, Any]]:
-    """Persists looked-up order_id and mock mode flag into session state after lookup_mock_merch_order."""
-    state = callback_context.state
-    state["is_mock_mode"] = True
-    resolved_order = (
-        str(tool_response.get("order_id") or input.get("order_id") or "")
-        .strip()
-        .lstrip("#")
-    )
-    if resolved_order:
-        state["order_id"] = resolved_order
-    return None
--- commit:b48bd74/cxas_app/agents/merch_support_agent/merch_support_agent.json
+++ live-export/cxas_app/agents/merch_support_agent/merch_support_agent.json
@@ -2,7 +2,7 @@
   "afterToolCallbacks": [
     {
       "description": "Persists looked-up order_id and is_mock_mode flag into session state after lookup_mock_merch_order.",
-      "pythonCode": "agents/merch_support_agent/after_tool_callbacks/sync_order_state/python_code.py"
+      "pythonCode": "agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py"
     }
   ],
   "description": "Specialist sub-agent for mocked Mercedes F1 merchandise order lookups, returns, exchanges, product availability, and damaged-item support.",
@@ -10,9 +10,9 @@
   "instruction": "agents/merch_support_agent/instruction.txt",
   "name": "c1111111-2222-3333-4444-555555555553",
   "tools": [
-    "lookup_mock_merch_order",
+    "end_session",
     "get_official_links",
     "get_race_schedule",
-    "end_session"
+    "lookup_mock_merch_order"
   ]
 }
--- commit:b48bd74/cxas_app/agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py
+++ live-export/cxas_app/agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py
@@ -0,0 +1,19 @@
+from typing import Any, Optional
+
+
+def after_tool_callback(
+    tool: Tool,
+    input: dict[str, Any],
+    callback_context: CallbackContext,
+    tool_response: dict[str, Any],
+) -> Optional[dict[str, Any]]:
+    """Persists resolved timezone and user location into session state after get_race_schedule."""
+    state = callback_context.state
+    req_tz = str(input.get("user_timezone") or "").strip()
+    resolved_tz = str(tool_response.get("timezone_resolved") or "").strip()
+    if req_tz and req_tz.upper() not in ("", "UTC", "UNKNOWN"):
+        state["user_timezone"] = resolved_tz or req_tz
+        state["user_location"] = req_tz
+    elif "user_timezone" not in state:
+        state["user_timezone"] = resolved_tz or "UTC"
+    return None
--- commit:b48bd74/cxas_app/agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py
+++ live-export/cxas_app/agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py
@@ -1,19 +0,0 @@
-from typing import Any, Optional
-
-
-def after_tool_callback(
-    tool: Tool,
-    input: dict[str, Any],
-    callback_context: CallbackContext,
-    tool_response: dict[str, Any],
-) -> Optional[dict[str, Any]]:
-    """Persists resolved timezone and user location into session state after get_race_schedule."""
-    state = callback_context.state
-    req_tz = str(input.get("user_timezone") or "").strip()
-    resolved_tz = str(tool_response.get("timezone_resolved") or "").strip()
-    if req_tz and req_tz.upper() not in ("", "UTC", "UNKNOWN"):
-        state["user_timezone"] = resolved_tz or req_tz
-        state["user_location"] = req_tz
-    elif "user_timezone" not in state:
-        state["user_timezone"] = resolved_tz or "UTC"
-    return None
--- commit:b48bd74/cxas_app/agents/race_info_agent/race_info_agent.json
+++ live-export/cxas_app/agents/race_info_agent/race_info_agent.json
@@ -2,7 +2,7 @@
   "afterToolCallbacks": [
     {
       "description": "Persists resolved user_timezone and user_location into session state after get_race_schedule.",
-      "pythonCode": "agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py"
+      "pythonCode": "agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py"
     }
   ],
   "description": "Specialist sub-agent for Formula 1 race schedules, weekend sessions, circuit weather, driver/constructor standings, recent Mercedes performance, and official race ticket links.",
@@ -10,9 +10,9 @@
   "instruction": "agents/race_info_agent/instruction.txt",
   "name": "c1111111-2222-3333-4444-555555555552",
   "tools": [
-    "get_race_schedule",
+    "end_session",
     "get_driver_standings",
     "get_official_links",
-    "end_session"
+    "get_race_schedule"
   ]
 }
--- commit:b48bd74/cxas_app/agents/ticketing_agent/ticketing_agent.json
+++ live-export/cxas_app/agents/ticketing_agent/ticketing_agent.json
@@ -4,8 +4,8 @@
   "instruction": "agents/ticketing_agent/instruction.txt",
   "name": "c1111111-2222-3333-4444-555555555554",
   "tools": [
+    "end_session",
     "get_official_links",
-    "get_race_schedule",
-    "end_session"
+    "get_race_schedule"
   ]
 }
--- commit:b48bd74/cxas_app/agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py
+++ live-export/cxas_app/agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py
@@ -0,0 +1,32 @@
+from typing import Optional
+import re
+
+
+ORDER_ID_PATTERN = re.compile(
+    r"(?:#|(?:order|commande|pedido|bestellung)\s+#?)([A-Za-z0-9-]{4,12})\b",
+    re.IGNORECASE,
+)
+
+
+def before_agent_callback(
+    callback_context: CallbackContext,
+) -> Optional[Content]:
+    """Initializes default session state variables and extracts any order ID generically."""
+    state = callback_context.state
+    if "is_mock_mode" not in state:
+        state["is_mock_mode"] = True
+    if "user_timezone" not in state:
+        state["user_timezone"] = ""
+    if "user_location" not in state:
+        state["user_location"] = ""
+    if "order_id" not in state:
+        state["order_id"] = ""
+
+    for part in callback_context.get_last_user_input():
+        text = part.text_or_transcript() or ""
+        match = ORDER_ID_PATTERN.search(text)
+        if match:
+            raw_id = match.group(1).strip()
+            digits_match = re.search(r"(\d{4,8})", raw_id)
+            state["order_id"] = digits_match.group(1) if digits_match else raw_id
+    return None
--- commit:b48bd74/cxas_app/agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py
+++ live-export/cxas_app/agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py
@@ -1,32 +0,0 @@
-from typing import Optional
-import re
-
-
-ORDER_ID_PATTERN = re.compile(
-    r"(?:#|(?:order|commande|pedido|bestellung)\s+#?)([A-Za-z0-9-]{4,12})\b",
-    re.IGNORECASE,
-)
-
-
-def before_agent_callback(
-    callback_context: CallbackContext,
-) -> Optional[Content]:
-    """Initializes default session state variables and extracts any order ID generically."""
-    state = callback_context.state
-    if "is_mock_mode" not in state:
-        state["is_mock_mode"] = True
-    if "user_timezone" not in state:
-        state["user_timezone"] = ""
-    if "user_location" not in state:
-        state["user_location"] = ""
-    if "order_id" not in state:
-        state["order_id"] = ""
-
-    for part in callback_context.get_last_user_input():
-        text = part.text_or_transcript() or ""
-        match = ORDER_ID_PATTERN.search(text)
-        if match:
-            raw_id = match.group(1).strip()
-            digits_match = re.search(r"(\d{4,8})", raw_id)
-            state["order_id"] = digits_match.group(1) if digits_match else raw_id
-    return None
--- commit:b48bd74/cxas_app/agents/totto_root_agent/totto_root_agent.json
+++ live-export/cxas_app/agents/totto_root_agent/totto_root_agent.json
@@ -2,12 +2,12 @@
   "beforeAgentCallbacks": [
     {
       "description": "Initializes session state variables (is_mock_mode, user_timezone, user_location, order_id) and extracts order_id from user messages.",
-      "pythonCode": "agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py"
+      "pythonCode": "agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py"
     }
   ],
   "childAgents": [
+    "merch_support_agent",
     "race_info_agent",
-    "merch_support_agent",
     "ticketing_agent"
   ],
   "description": "Root concierge for Totto, Mercedes F1 Fan Agent. Handles greetings, F1/Mercedes history, brand guardrails, official link referrals, multilingual responses, and silent specialist routing.",
@@ -15,7 +15,7 @@
   "instruction": "agents/totto_root_agent/instruction.txt",
   "name": "c1111111-2222-3333-4444-555555555551",
   "tools": [
-    "get_official_links",
-    "end_session"
+    "end_session",
+    "get_official_links"
   ]
 }
--- commit:b48bd74/cxas_app/app.json
+++ live-export/cxas_app/app.json
@@ -2,6 +2,11 @@
   "description": "Voice-first, multilingual Formula 1 fan concierge for the Mercedes-AMG PETRONAS Formula One Team.",
   "displayName": "totto-mercedes-f1-fan-agent",
   "globalInstruction": "global_instruction.txt",
+  "loggingSettings": {
+    "conversationLoggingSettings": {
+      "retentionWindow": "31536000s"
+    }
+  },
   "modelSettings": {
     "model": "gemini-3.0-flash-001"
   },
@@ -9,10 +14,16 @@
   "rootAgent": "totto_root_agent",
   "variableDeclarations": [
     {
-      "description": "User's local timezone (e.g. EST, PST, Europe/London, Asia/Tokyo, Australia/Sydney, UTC).",
-      "name": "user_timezone",
+      "description": "Flag indicating simulated demo mode for merchandise support.",
+      "name": "is_mock_mode",
       "schema": {
-        "required": [],
+        "type": "BOOLEAN"
+      }
+    },
+    {
+      "description": "4-digit mock merchandise order number (1001, 1002, 1003, 9999).",
+      "name": "order_id",
+      "schema": {
         "type": "STRING"
       }
     },
@@ -20,24 +31,14 @@
       "description": "User's city, country, or region.",
       "name": "user_location",
       "schema": {
-        "required": [],
         "type": "STRING"
       }
     },
     {
-      "description": "4-digit mock merchandise order number (1001, 1002, 1003, 9999).",
-      "name": "order_id",
+      "description": "User's local timezone (e.g. EST, PST, Europe/London, Asia/Tokyo, Australia/Sydney, UTC).",
+      "name": "user_timezone",
       "schema": {
-        "required": [],
         "type": "STRING"
-      }
-    },
-    {
-      "description": "Flag indicating simulated demo mode for merchandise support.",
-      "name": "is_mock_mode",
-      "schema": {
-        "required": [],
-        "type": "BOOLEAN"
       }
     }
   ]
--- commit:b48bd74/cxas_app/pythonEnvFiles/pythonEnvFiles.json
+++ live-export/cxas_app/pythonEnvFiles/pythonEnvFiles.json
@@ -0,0 +1 @@
+{}
--- commit:b48bd74/cxas_app/tools/get_driver_standings/get_driver_standings.json
+++ live-export/cxas_app/tools/get_driver_standings/get_driver_standings.json
@@ -3,7 +3,7 @@
   "executionType": "SYNCHRONOUS",
   "name": "d1111111-2222-3333-4444-555555555552",
   "pythonFunction": {
-    "description": "Fetches Formula 1 Driver and Constructor Championship standings with Mercedes-AMG PETRONAS F1 Team, George Russell, and Kimi Antonelli highlighted first.",
+    "description": "Retrieves Formula 1 Constructor and Driver Championship standings with Mercedes context first.\n\nArgs:\n    season: Championship year (default 2026, valid range 1950-2030).\n    category: Standings filter ('all', 'both', 'drivers', 'constructors', or 'mercedes').\n\nReturns:\n    Dictionary containing Mercedes-first constructor and driver standings and recent performance.",
     "name": "get_driver_standings",
     "pythonCode": "tools/get_driver_standings/python_function/python_code.py"
   }
--- commit:b48bd74/cxas_app/tools/get_official_links/get_official_links.json
+++ live-export/cxas_app/tools/get_official_links/get_official_links.json
@@ -3,7 +3,7 @@
   "executionType": "SYNCHRONOUS",
   "name": "d1111111-2222-3333-4444-555555555554",
   "pythonFunction": {
-    "description": "Returns verified official URLs for Formula 1 ticketing (https://tickets.formula1.com), the official Mercedes-AMG PETRONAS F1 Store (https://shop.mercedesamgf1.com), and the official team portal (https://www.mercedesamgf1.com).",
+    "description": "Retrieves verified official links for Formula 1 ticketing, Mercedes F1 store, and team channels.\n\nArgs:\n    category: Link category ('ticketing', 'merch', 'team', or 'all').\n\nReturns:\n    Dictionary containing verified official URLs and non-transactional guidance.",
     "name": "get_official_links",
     "pythonCode": "tools/get_official_links/python_function/python_code.py"
   }
--- commit:b48bd74/cxas_app/tools/get_race_schedule/get_race_schedule.json
+++ live-export/cxas_app/tools/get_race_schedule/get_race_schedule.json
@@ -3,7 +3,7 @@
   "executionType": "SYNCHRONOUS",
   "name": "d1111111-2222-3333-4444-555555555551",
   "pythonFunction": {
-    "description": "Fetches Formula 1 race weekend schedules, session start times (Practice 1, Practice 2, Practice 3, Qualifying, Grand Prix), timezone conversions via zoneinfo, circuit info, weather forecast, and Mercedes highlights.",
+    "description": "Fetches Formula 1 race schedule, session times, weather forecast, and Mercedes context.\n\nArgs:\n    race_query: Name of the Grand Prix (e.g., 'next', 'Singapore Grand Prix', 'British Grand Prix').\n    user_timezone: User's timezone or city (e.g., 'EST', 'America/New_York', 'Sydney', 'Asia/Tokyo').\n\nReturns:\n    Dictionary containing structured race weekend sessions, weather, and Mercedes highlights.",
     "name": "get_race_schedule",
     "pythonCode": "tools/get_race_schedule/python_function/python_code.py"
   }
--- commit:b48bd74/cxas_app/tools/lookup_mock_merch_order/lookup_mock_merch_order.json
+++ live-export/cxas_app/tools/lookup_mock_merch_order/lookup_mock_merch_order.json
@@ -3,7 +3,7 @@
   "executionType": "SYNCHRONOUS",
   "name": "d1111111-2222-3333-4444-555555555553",
   "pythonFunction": {
-    "description": "Looks up mocked Mercedes-AMG PETRONAS F1 merchandise orders (#1001, #1002, #1003, #9999) for order status, returns, exchanges, product availability, and damaged-item support.",
+    "description": "Looks up a mocked Mercedes F1 merchandise order by order number.\n\nArgs:\n    order_id: 4-digit mock order number (e.g. '1001', '1002', '1003', or '9999').\n\nReturns:\n    Dictionary with mocked order status, return/exchange/damaged-item policies, and mock disclosure.",
     "name": "lookup_mock_merch_order",
     "pythonCode": "tools/lookup_mock_merch_order/python_function/python_code.py"
   }
```

## `f073e02` totto_agent: OpenF1 API + zoneinfo timezones + anti-hardcoding fixes (30/30 SCRAPI + 10/10 probes)

Identical after normalization.
Raw (un-normalized) view: differing `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_official_links/get_official_links.json`, `tools/get_race_schedule/get_race_schedule.json`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`; only in commit `agents/merch_support_agent/after_tool_callbacks/sync_order_state/python_code.py`, `agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py`; only in live `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `pythonEnvFiles/pythonEnvFiles.json`

## `a7c3094` chore(eval): record Iteration 3 auto-revert diagnostics, dashboard, release notes, and TEST_READY

Differing files: `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`
Only in live export: `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`
Raw (un-normalized) view: differing `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`; only in commit none; only in live `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`, `pythonEnvFiles/pythonEnvFiles.json`
(unified diffs for this commit are in diff_vs_commits.json)

## `1a17988` iter(2): Add timezone clarification gate, rival-respect & PCI guardrails, damaged-item flows, and cross-agent topic-switch routing [public: 18/18 (100.0%), holdout: 16/16 (100.0%), overall: 100.0%]

Differing files: `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`
Only in live export: `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`
Raw (un-normalized) view: differing `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`; only in commit none; only in live `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`, `pythonEnvFiles/pythonEnvFiles.json`
(unified diffs for this commit are in diff_vs_commits.json)

## `bdb8f3b` iter(1): Initial 4-agent Totto scaffold and 4 Python tools baseline [public: 12/18 (66.7%), holdout: 6/16 (37.5%), overall: 61.9%]

Differing files: `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`
Only in live export: `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`
Raw (un-normalized) view: differing `agents/merch_support_agent/instruction.txt`, `agents/merch_support_agent/merch_support_agent.json`, `agents/race_info_agent/instruction.txt`, `agents/race_info_agent/race_info_agent.json`, `agents/ticketing_agent/instruction.txt`, `agents/ticketing_agent/ticketing_agent.json`, `agents/totto_root_agent/instruction.txt`, `agents/totto_root_agent/totto_root_agent.json`, `app.json`, `tools/get_driver_standings/get_driver_standings.json`, `tools/get_driver_standings/python_function/python_code.py`, `tools/get_official_links/get_official_links.json`, `tools/get_official_links/python_function/python_code.py`, `tools/get_race_schedule/get_race_schedule.json`, `tools/get_race_schedule/python_function/python_code.py`, `tools/lookup_mock_merch_order/lookup_mock_merch_order.json`, `tools/lookup_mock_merch_order/python_function/python_code.py`; only in commit none; only in live `agents/merch_support_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/race_info_agent/after_tool_callbacks/after_tool_callbacks_01/python_code.py`, `agents/totto_root_agent/before_agent_callbacks/before_agent_callbacks_01/python_code.py`, `global_instruction.txt`, `pythonEnvFiles/pythonEnvFiles.json`
(unified diffs for this commit are in diff_vs_commits.json)
