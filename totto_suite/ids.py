"""App-relative platform IDs and target-app resolution.

Records never store full resource names (they embed the GCP project and the
CXAS app UUID). Instead they store IDs relative to the app, e.g.
``evaluationRuns/<uuid>``, ``evaluations/<e>/results/<r>``,
``conversations/<uuid>``, ``sessions/<uuid>``, ``tools/<uuid>``,
``versions/<uuid>``, plus an ``app_ref`` (``staging``, ``live`` or
``explicit``) that says which app they belong to. ``verify-ids --app-name``
prefixes them with the full app name at verification time.

Records written before this scheme ("legacy") stored full names, often with
a sanitized placeholder project; :func:`is_legacy_id` flags those.
"""

from __future__ import annotations

import os
import re
from typing import Any

from totto_suite import config

APP_REFS = ("staging", "live", "explicit")

_APP_PREFIX_RE = re.compile(r"^projects/[^/]+/locations/[^/]+/apps/[^/]+/(?P<rest>.+)$")
_LEGACY_PLACEHOLDER_RE = re.compile(
    r"^projects/your-gcp-project/|/apps/00000000-0000-0000-0000-000000000000(/|$)"
)

# platform_ids keys whose values are bare UUIDs (not resource paths).
_BARE_ID_COLLECTION = {
    "session_id": "sessions",
    "app_version": "versions",
}


def to_app_relative(name: str | None) -> str:
    """``projects/p/locations/l/apps/a/evaluationRuns/x`` -> ``evaluationRuns/x``.

    Already-relative values are returned unchanged; empty input gives ``""``.
    """
    if not name:
        return ""
    text = str(name).strip()
    m = _APP_PREFIX_RE.match(text)
    return m.group("rest") if m else text


def relative_id(key: str, value: Any) -> str:
    """Canonical app-relative form of one ``platform_ids`` entry."""
    rel = to_app_relative(str(value or ""))
    if not rel:
        return ""
    collection = _BARE_ID_COLLECTION.get(key)
    if collection and "/" not in rel:
        return f"{collection}/{rel}"
    return rel


def relativize_platform_ids(pids: dict[str, Any] | None) -> dict[str, str]:
    """Maps every value of a ``platform_ids`` dict to its app-relative form."""
    out: dict[str, str] = {}
    for key, value in (pids or {}).items():
        rel = relative_id(key, value)
        if rel:
            out[key] = rel
    return out


def to_full(app_name: str, rel: str) -> str:
    """Prefixes an app-relative ID with ``app_name`` (full names pass through)."""
    text = str(rel or "").strip()
    if not text or text.startswith("projects/"):
        return text
    return f"{app_name.rstrip('/')}/{text}"


def last_segment(rel: str) -> str:
    return str(rel or "").rstrip("/").rsplit("/", 1)[-1]


def is_legacy_id(value: str | None) -> bool:
    """True for full resource names (pre app-relative records)."""
    return bool(value) and str(value).startswith("projects/")


def is_placeholder_id(value: str | None) -> bool:
    """True for legacy IDs that were sanitized and can never be fetched."""
    return bool(value) and bool(_LEGACY_PLACEHOLDER_RE.search(str(value)))


_ANY_APP_PREFIX_RE = re.compile(r"projects/[^/\s\"']+/locations/[^/\s\"']+/apps/[^/\s\"']+/?")
_ANY_PROJECT_PREFIX_RE = re.compile(r"projects/[^/\s\"']+/locations/[^/\s\"']+")


def redact_text(text: str, app_name: str | None = None) -> str:
    """Strips project/app identifiers from free text (errors, payload dumps).

    Full app-scoped resource names become app-relative (``<app>/`` prefix
    dropped to ``""``), other project paths become ``projects/<project>/...``
    and the bare project / app IDs of ``app_name`` are replaced.
    """
    if not text:
        return text
    out = _ANY_APP_PREFIX_RE.sub("", str(text))
    out = _ANY_PROJECT_PREFIX_RE.sub("projects/<project>/locations/<location>", out)
    if app_name:
        try:
            parts = config.parse_app_name(app_name)
        except ValueError:
            parts = {}
        for key, label in (("app_id", "<app-id>"), ("project", "<project>")):
            value = parts.get(key)
            if value and len(value) >= 6:
                out = out.replace(value, label)
    return out


def redact_obj(obj: Any, app_name: str | None = None) -> Any:
    """Recursively applies :func:`redact_text` to every string in ``obj``."""
    if isinstance(obj, str):
        return redact_text(obj, app_name)
    if isinstance(obj, dict):
        return {k: redact_obj(v, app_name) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, app_name) for v in obj]
    if isinstance(obj, tuple):
        return [redact_obj(v, app_name) for v in obj]
    return obj


def resolve_app_name(
    app_name: str | None = None,
    target: str = "explicit",
    environ: dict[str, str] | None = None,
    local_cfg: dict[str, str] | None = None,
) -> str:
    """Resolves the target app without hard-coding any identifier.

    Order: explicit ``app_name`` > ``$TOTTO_APP_NAME`` >
    ``projects/$GCP_PROJECT_ID/locations/$CXAS_LOCATION/apps/$CXAS_APP_ID`` >
    gitignored ``gecx-config.json`` (``staging_app_id`` for target=staging,
    ``app_id`` otherwise). Raises ValueError when nothing is configured.
    """
    env = os.environ if environ is None else environ
    cfg = config._LOCAL_CFG if local_cfg is None else local_cfg  # noqa: SLF001
    candidates: list[str] = []
    if app_name:
        candidates.append(app_name.strip())
    if env.get("TOTTO_APP_NAME", "").strip():
        candidates.append(env["TOTTO_APP_NAME"].strip())
    project = env.get("GCP_PROJECT_ID", "").strip()
    location = env.get("CXAS_LOCATION", "").strip() or "us"
    app_id = env.get("CXAS_APP_ID", "").strip()
    if project and app_id:
        candidates.append(f"projects/{project}/locations/{location}/apps/{app_id}")
    cfg_project = str(cfg.get("gcp_project_id", "") or "").strip()
    cfg_location = str(cfg.get("location", "") or "").strip() or "us"
    key = "staging_app_id" if target == "staging" else "app_id"
    cfg_app = str(cfg.get(key, "") or "").strip()
    if cfg_project and cfg_app:
        candidates.append(f"projects/{cfg_project}/locations/{cfg_location}/apps/{cfg_app}")
    for cand in candidates:
        config.parse_app_name(cand)  # raises ValueError on malformed names
        return cand
    raise ValueError(
        "no target app: pass --app-name projects/<p>/locations/<l>/apps/<id> or set "
        "TOTTO_APP_NAME (or GCP_PROJECT_ID + CXAS_APP_ID)"
    )


def configured_identifiers(
    environ: dict[str, str] | None = None,
    local_cfg: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Identifier values that must never be written: ``{value: label}``.

    Collected from the environment (``TOTTO_APP_NAME``, ``GCP_PROJECT_ID``,
    ``CXAS_APP_ID``, ``CXAS_STAGING_APP_ID``, ``GCP_PROJECT_NUMBER``) and the
    gitignored gecx-config.json (project id/number, live and staging app id).
    Values shorter than 6 characters are ignored (too likely to collide).
    """
    env = os.environ if environ is None else environ
    cfg = config._LOCAL_CFG if local_cfg is None else local_cfg  # noqa: SLF001
    pairs = [
        (env.get("GCP_PROJECT_ID"), "<project>"),
        (env.get("GCP_PROJECT_NUMBER"), "<project-number>"),
        (env.get("CXAS_APP_ID"), "<app-id>"),
        (env.get("CXAS_STAGING_APP_ID"), "<staging-app-id>"),
        (cfg.get("gcp_project_id"), "<project>"),
        (cfg.get("project_number"), "<project-number>"),
        (cfg.get("app_id"), "<app-id>"),
        (cfg.get("deployed_app_id"), "<app-id>"),
        (cfg.get("staging_app_id"), "<staging-app-id>"),
    ]
    name = str(env.get("TOTTO_APP_NAME", "") or "").strip()
    if name:
        try:
            parts = config.parse_app_name(name)
            pairs += [(parts["project"], "<project>"), (parts["app_id"], "<app-id>")]
        except ValueError:
            pass
    out: dict[str, str] = {}
    for value, label in pairs:
        text = str(value or "").strip()
        if len(text) >= 6 and text not in out:
            out[text] = label
    return out


_CONFIGURED_APP_PATH_RE_CACHE: dict[tuple[str, ...], re.Pattern[str]] = {}


def scrub_configured(obj: Any, identifiers: dict[str, str] | None = None) -> Any:
    """Removes configured identifiers from every string in ``obj``.

    Full resource names of a configured app lose their ``projects/../apps/..``
    prefix (becoming app-relative); remaining bare values are replaced by a
    label. Legacy placeholder names are left untouched.
    """
    idents = configured_identifiers() if identifiers is None else identifiers
    if not idents:
        return obj
    key = tuple(sorted(idents))
    pattern = _CONFIGURED_APP_PATH_RE_CACHE.get(key)
    if pattern is None:
        alts = "|".join(re.escape(v) for v in sorted(idents, key=len, reverse=True))
        pattern = re.compile(
            rf"projects/(?:{alts})/locations/[^/\s\"']+/apps/[^/\s\"']+(?P<slash>/?)"
            rf"|projects/[^/\s\"']+/locations/[^/\s\"']+/apps/(?:{alts})(?P<slash2>/?)"
        )
        _CONFIGURED_APP_PATH_RE_CACHE[key] = pattern

    def scrub(text: str) -> str:
        out = pattern.sub(lambda m: "" if (m.group("slash") or m.group("slash2")) else "<app>", text)
        for value in sorted(idents, key=len, reverse=True):
            if value in out:
                out = out.replace(value, idents[value])
        return out

    def visit(node: Any) -> Any:
        if isinstance(node, str):
            return scrub(node)
        if isinstance(node, dict):
            return {k: visit(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [visit(v) for v in node]
        return node

    return visit(obj)


def find_configured(text: str, identifiers: dict[str, str] | None = None) -> list[str]:
    """Labels of configured identifiers present in ``text`` (never the values)."""
    idents = configured_identifiers() if identifiers is None else identifiers
    return sorted({label for value, label in idents.items() if value in text})


_ANY_APP_PATH_RE = re.compile(
    r"projects/(?P<project>[^/\s\"']+)/locations/(?P<loc>[^/\s\"']+)/apps/(?P<app>[^/\s\"']+)"
)


def mask_text(
    text: str,
    app_name: str | None = None,
    identifiers: dict[str, str] | None = None,
) -> str:
    """Masks ONLY project / project-number / app IDs, keeping resource paths.

    For logs (CI Actions output): ``projects/p/locations/us/apps/a/evaluationRuns/u``
    becomes ``projects/<project>/locations/us/apps/<app-id>/evaluationRuns/u``, so
    evaluation-run / session / conversation / result UUIDs stay visible and can be
    matched against ``verify-ids`` evidence. Bare configured values (and the
    project / app of ``app_name``) are replaced by their labels as well.
    """
    if not text:
        return text
    idents = dict(configured_identifiers() if identifiers is None else identifiers)
    if app_name:
        try:
            parts = config.parse_app_name(app_name)
        except ValueError:
            parts = {}
        for key, label in (("project", "<project>"), ("app_id", "<app-id>")):
            value = str(parts.get(key) or "")
            if len(value) >= 6:
                idents.setdefault(value, label)

    def path(m: re.Match[str]) -> str:
        app = idents.get(m.group("app"), "<app-id>")
        return f"projects/<project>/locations/{m.group('loc')}/apps/{app}"

    out = _ANY_APP_PATH_RE.sub(path, str(text))
    for value in sorted(idents, key=len, reverse=True):
        if value in out:
            out = out.replace(value, idents[value])
    return out


def app_ref_for(value: Any, identifiers: dict[str, str] | None = None) -> Any:
    """Normalizes a record's ``cxas.app`` to an app_ref.

    ``staging``/``live``/``explicit`` pass through, a full name of a
    configured app becomes ``staging`` or ``live``, any other full name
    ``explicit``; legacy placeholders and empty values are kept as they are.
    """
    text = str(value or "").strip()
    if not text or text in APP_REFS or is_placeholder_id(text):
        return value
    idents = configured_identifiers() if identifiers is None else identifiers
    labels = {idents.get(seg) for seg in text.split("/")}
    if "<staging-app-id>" in labels:
        return "staging"
    if "<app-id>" in labels:
        return "live"
    return "explicit"
