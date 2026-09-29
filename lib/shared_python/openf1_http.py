# Shared OpenF1 HTTP helpers used by the get_race_schedule and get_driver_standings tools.
# CXAS runs each tool as one self-contained file, so scripts/bundle_shared_imports.py copies
# this fragment verbatim between the "SHARED openf1_http" markers of both tools.
# The host file must import: json, sys, urllib.request and typing.Any.

OPENF1_BASE_URL = "https://api.openf1.org/v1"


def _get_cache() -> dict[str, Any]:
    cache = getattr(sys, "_totto_openf1_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(sys, "_totto_openf1_cache", cache)
    return cache


def _fetch_openf1_json(endpoint: str) -> list[dict[str, Any]]:
    cache = _get_cache()
    cache_key = f"openf1:{endpoint}"
    if cache_key in cache:
        return cache[cache_key]

    url = f"{OPENF1_BASE_URL}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "TottoFanAgent/2.0"}
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        raw_bytes = resp.read()
    parsed = json.loads(raw_bytes.decode("utf-8"))
    if isinstance(parsed, list):
        cache[cache_key] = parsed
        return parsed
    return []
