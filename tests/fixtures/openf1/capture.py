"""One-time capture of OpenF1 payloads used as offline test fixtures.

Run manually (it is the ONLY network access of the offline suite; tests never
touch the network):

    .venv/bin/python tests/fixtures/openf1/capture.py

It writes one JSON file per endpoint next to this script plus ``metadata.json``
recording, for every file, the exact URL, the UTC fetch time, the HTTP status,
the item count and the sha256 of the bytes written. Payloads are stored exactly
as returned by the API (re-serialised with sorted keys for stable diffs); no
value is edited. If the API is unreachable or rate-limits, the script stops
and exits non-zero without writing partial fixtures (never fabricate data).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://api.openf1.org/v1"
OUT_DIR = Path(__file__).resolve().parent
PAUSE_S = 1.5  # stay well below OpenF1's free-tier request rate limits

# (file stem, endpoint). Weather endpoints are added after sessions are known.
ENDPOINTS = [
    ("meetings_2026", "meetings?year=2026"),
    ("sessions_2026", "sessions?year=2026"),
    ("championship_drivers_latest", "championship_drivers?session_key=latest"),
    ("championship_teams_latest", "championship_teams?session_key=latest"),
    ("drivers_latest", "drivers?session_key=latest"),
]


def fetch(endpoint: str) -> tuple[int, bytes]:
    url = f"{BASE_URL}/{endpoint}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "totto-suite-fixture-capture/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https URL)
        return resp.status, resp.read()


def race_session_keys(sessions: list[dict], meetings: list[dict], now: dt.datetime) -> list[tuple[int, int]]:
    """Returns [(meeting_key, race session_key)] for the first and the last completed race."""
    names = {m.get("meeting_key"): m.get("meeting_name", "") for m in meetings}
    done = []
    for s in sessions:
        if s.get("session_name") != "Race" or s.get("session_type") != "Race":
            continue
        end = s.get("date_end")
        if not end:
            continue
        end_dt = dt.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if end_dt < now and "Grand Prix" in str(names.get(s.get("meeting_key"), "")):
            done.append((end_dt, int(s["meeting_key"]), int(s["session_key"])))
    done.sort()
    picks = []
    if done:
        picks.append(done[0][1:])
        if done[-1][1:] != done[0][1:]:
            picks.append(done[-1][1:])
    return picks


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    captured: dict[str, dict] = {}
    payloads: dict[str, bytes] = {}
    endpoints = list(ENDPOINTS)
    i = 0
    while i < len(endpoints):
        stem, endpoint = endpoints[i]
        i += 1
        fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            status, body = fetch(endpoint)
        except urllib.error.HTTPError as e:
            print(f"STOP: HTTP {e.code} for {endpoint}: {e.reason}", file=sys.stderr)
            return 2
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"STOP: network error for {endpoint}: {e}", file=sys.stderr)
            return 2
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, list) or not data:
            print(f"STOP: {endpoint} returned no list data: {str(data)[:200]}", file=sys.stderr)
            return 3
        text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        payloads[stem] = text.encode("utf-8")
        captured[stem] = {
            "file": f"{stem}.json",
            "url": f"{BASE_URL}/{endpoint}",
            "fetched_at_utc": fetched_at,
            "http_status": status,
            "items": len(data),
            "raw_response_bytes": len(body),
            "sha256_of_file": hashlib.sha256(payloads[stem]).hexdigest(),
        }
        print(f"ok {endpoint}: {len(data)} items")
        if stem == "sessions_2026":
            meetings = json.loads(payloads["meetings_2026"])
            for mk, sk in race_session_keys(data, meetings, now):
                endpoints.append((f"weather_meeting_{mk}_race_session_{sk}", f"weather?session_key={sk}"))
        time.sleep(PAUSE_S)

    for stem, body in payloads.items():
        (OUT_DIR / f"{stem}.json").write_bytes(body)
    meta = {
        "description": (
            "Raw OpenF1 API payloads captured once for the offline Totto test suite. "
            "Tests load these files instead of the network."
        ),
        "capture_script": "tests/fixtures/openf1/capture.py",
        "captured_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": captured,
    }
    (OUT_DIR / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
