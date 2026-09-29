"""CXAS API access for the suite: READ, inline EXPORT and VERSION SNAPSHOTS only.

R5 (ORIGINAL_REQUEST 21:13:03Z) forbids pushing, changing, restoring or
deleting anything on the live app. This module therefore wraps only:

* reads: get_app, list/get versions, list evaluations / evaluation runs,
  list/get conversations;
* ``export_app`` with ``gcs_uri=None`` (inline bytes, no Cloud Storage);
* ``create_version`` (a snapshot; explicitly allowed).

It also holds the pure, offline helpers that turn an export into the repo
layout and compare it with a repo ``cxas_app`` (normalization rules below).
SCRAPI is imported lazily so offline commands never pay for it.
"""

from __future__ import annotations

import ast
import datetime
import difflib
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

from totto_suite import config


# --------------------------------------------------------------------------
# Live reads / export / version snapshot (lazy SCRAPI imports)
# --------------------------------------------------------------------------


def _apps(app_name: str):
    from cxas_scrapi.core.apps import Apps  # pylint: disable=import-outside-toplevel

    parts = config.parse_app_name(app_name)
    return Apps(project_id=parts["project"], location=parts["location"])


def _versions(app_name: str):
    from cxas_scrapi.core.versions import Versions  # pylint: disable=import-outside-toplevel

    return Versions(app_name=app_name)


def _to_dict(message) -> dict:
    """proto-plus / protobuf message -> JSON-safe dict (camelCase keys)."""
    from google.protobuf import json_format  # pylint: disable=import-outside-toplevel

    pb = getattr(type(message), "pb", None)
    raw = pb(message) if callable(pb) else message
    return json_format.MessageToDict(raw, preserving_proto_field_name=False)


def _ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
    return str(value)


def get_app(app_name: str | None = None) -> dict:
    """Returns the app as a dict plus normalized ``update_time``/``etag``."""
    app_name = app_name or config.app_name()
    app = _apps(app_name).get_app(app_name)
    d = _to_dict(app)
    return {
        "name": app.name,
        "display_name": app.display_name,
        "update_time": _ts(app.update_time),
        "create_time": _ts(app.create_time),
        "etag": app.etag,
        "raw": d,
    }


def version_to_dict(v) -> dict:
    return {
        "name": v.name,
        "id": v.name.rsplit("/", 1)[-1],
        "display_name": v.display_name,
        "description": v.description,
        "create_time": _ts(v.create_time),
    }


def list_versions(app_name: str | None = None) -> list[dict]:
    app_name = app_name or config.app_name()
    return [version_to_dict(v) for v in _versions(app_name).list_versions()]


def get_version(version_id: str, app_name: str | None = None) -> dict:
    """Fetches one version by bare ID (works for hidden evaluation versions)."""
    app_name = app_name or config.app_name()
    version_id = version_id.rsplit("/", 1)[-1]
    return version_to_dict(_versions(app_name).get_version(version_id))


def create_version(
    display_name: str, description: str, app_name: str | None = None
) -> dict:
    """Creates a version snapshot (allowed by R5). The API may return an
    existing identical version instead of a new one; callers must check."""
    app_name = app_name or config.app_name()
    v = _versions(app_name).create_version(
        display_name=display_name, description=description
    )
    return version_to_dict(v)


def _evaluation_client(app_name: str):
    from cxas_scrapi.core.evaluations import Evaluations  # pylint: disable=import-outside-toplevel

    return Evaluations(app_name=app_name)


def list_evaluations(app_name: str | None = None) -> list[dict]:
    from google.cloud.ces_v1beta import types  # pylint: disable=import-outside-toplevel

    app_name = app_name or config.app_name()
    ev = _evaluation_client(app_name)
    req = types.ListEvaluationsRequest(parent=app_name)
    return [
        {
            "name": e.name,
            "display_name": e.display_name,
            "create_time": _ts(getattr(e, "create_time", None)),
        }
        for e in ev.client.list_evaluations(request=req)
    ]


def list_evaluation_runs(app_name: str | None = None) -> list[dict]:
    from google.cloud.ces_v1beta import types  # pylint: disable=import-outside-toplevel

    app_name = app_name or config.app_name()
    ev = _evaluation_client(app_name)
    req = types.ListEvaluationRunsRequest(parent=app_name)
    out = []
    for r in ev.client.list_evaluation_runs(request=req):
        out.append(
            {
                "name": r.name,
                "display_name": getattr(r, "display_name", ""),
                "create_time": _ts(getattr(r, "create_time", None)),
                "state": str(getattr(r, "state", "")),
                "app_version": getattr(r, "app_version", "") or "",
            }
        )
    return out


def _history(app_name: str):
    from cxas_scrapi.core.conversation_history import ConversationHistory  # pylint: disable=import-outside-toplevel

    return ConversationHistory(app_name=app_name, transport="rest")


def list_conversations(
    time_filter: str = "24h",
    source: str | None = None,
    app_name: str | None = None,
) -> list[dict]:
    """Conversations started within ``time_filter`` (optionally one source)."""
    app_name = app_name or config.app_name()
    convs = _history(app_name).list_conversations(
        time_filter=time_filter, source_filter=source
    )
    return [
        {
            "name": c.name,
            "id": c.name.rsplit("/", 1)[-1],
            "start_time": _ts(getattr(c, "start_time", None)),
            "source": getattr(getattr(c, "source", None), "name", str(c.source)),
            "channel_type": getattr(
                getattr(c, "channel_type", None), "name", str(c.channel_type)
            ),
            "turn_count": getattr(c, "turn_count", None),
            "app_version": getattr(c, "app_version", ""),
        }
        for c in convs
    ]


def get_conversation(conversation_id: str, app_name: str | None = None) -> dict:
    app_name = app_name or config.app_name()
    return _to_dict(_history(app_name).get_conversation(conversation_id))


def export_app_bytes(
    app_name: str | None = None, app_version: str | None = None
) -> bytes:
    """Inline export (``gcs_uri=None``: no Cloud Storage object is created)."""
    app_name = app_name or config.app_name()
    op = _apps(app_name).export_app(
        app_name, gcs_uri=None, local_path=None, app_version=app_version
    )
    return op.result(timeout=300).app_content


# --------------------------------------------------------------------------
# Offline helpers: export extraction, normalization, tree hash, diff
# --------------------------------------------------------------------------


def extract_export(zip_bytes: bytes, dest_app_dir: Path) -> list[str]:
    """Extracts an export zip so ``dest_app_dir`` has the repo layout.

    The export wraps everything in one top-level folder (the app display
    name); its contents become ``dest_app_dir``. Refuses to write into the
    repo's own ``cxas_app/`` (the agent under test is never modified).
    """
    dest_app_dir = Path(dest_app_dir).resolve()
    if dest_app_dir == config.DEFAULT_APP_DIR.resolve():
        raise ValueError("refusing to extract an export into the repo's cxas_app/")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        tops = {m.filename.split("/", 1)[0] for m in members}
        strip = len(tops) == 1 and all("/" in m.filename for m in members)
        written = []
        for m in members:
            rel = m.filename.split("/", 1)[1] if strip else m.filename
            target = (dest_app_dir / rel).resolve()
            if dest_app_dir not in target.parents:
                raise ValueError(f"unsafe path in export zip: {m.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(m))
            written.append(Path(rel).as_posix())
    return sorted(written)


# Files that are local configuration, never part of the pushed app content
# (they are gitignored in the repo).
LOCAL_ONLY_FILES = ("gecx-config.json", "environment.json")
# Callback list keys in agent JSON; order matters (execution order), so the
# lists are never sorted, only their file paths canonicalized.
CALLBACK_KEYS = (
    "beforeAgentCallbacks",
    "afterAgentCallbacks",
    "beforeModelCallbacks",
    "afterModelCallbacks",
    "beforeToolCallbacks",
    "afterToolCallbacks",
)
# Lists that are sets (membership, not order, is the semantics).
SET_LIST_KEYS = ("tools", "childAgents", "toolsets", "guardrails")
KEYED_LIST_KEYS = {"variableDeclarations": "name"}
# app.json keys managed by the platform, not by the agent content.
SERVER_MANAGED_APP_KEYS = ("loggingSettings",)

NORMALIZATION_RULES = [
    "N0 skip __pycache__/, *.pyc and local-only config files "
    + ", ".join(LOCAL_ONLY_FILES),
    "N1 callback code files are renamed to the server layout"
    " agents/<agent>/<callback_kind>/<callback_kind>_<NN>/python_code.py"
    " (NN = 1-based position in the agent JSON list) and the JSON pythonCode"
    " paths rewritten; list order is preserved",
    "N2 tool pythonFunction.description is set to the docstring of the"
    " function in the tool's python code (the server derives it on import)",
    "N3 set-valued lists sorted: " + ", ".join(SET_LIST_KEYS)
    + "; variableDeclarations sorted by name",
    "N4 empty values ([], {}, \"\", null) dropped (proto3 JSON omits them)",
    "N5 app.json platform-managed keys removed and reported separately: "
    + ", ".join(SERVER_MANAGED_APP_KEYS),
    "N6 JSON files that are empty after N4 are dropped (e.g."
    " pythonEnvFiles/pythonEnvFiles.json = {})",
    "N7 JSON re-serialized with sorted keys and 2-space indent; text files"
    " use LF line endings and exactly one trailing newline",
]


def _snake_callback_kind(key: str) -> str:
    out = []
    for ch in key:
        if ch.isupper():
            out.append("_" + ch.lower())
        else:
            out.append(ch)
    return "".join(out).lstrip("_")


def _drop_empty(value):
    if isinstance(value, dict):
        cleaned = {k: _drop_empty(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in ([], {}, "", None)}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value


def _sort_sets(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = _sort_sets(v)
            if k in SET_LIST_KEYS and isinstance(v, list) and all(
                isinstance(x, str) for x in v
            ):
                v = sorted(v)
            elif k in KEYED_LIST_KEYS and isinstance(v, list) and all(
                isinstance(x, dict) for x in v
            ):
                key = KEYED_LIST_KEYS[k]
                v = sorted(v, key=lambda x: str(x.get(key, "")))
            out[k] = v
        return out
    if isinstance(value, list):
        return [_sort_sets(v) for v in value]
    return value


def _docstring(code: str, func_name: str) -> str | None:
    try:
        mod = ast.parse(code)
    except SyntaxError:
        return None
    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == func_name
        ):
            return ast.get_docstring(node)
    return None


def _read_tree(root: Path) -> dict[str, bytes]:
    files = {}
    root = Path(root)
    if not root.is_dir():
        return files
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        parts = rel.split("/")
        if "__pycache__" in parts or rel.endswith(".pyc"):
            continue
        if rel in LOCAL_ONLY_FILES:
            continue
        files[rel] = p.read_bytes()
    return files


def normalize_app_tree(root: Path) -> dict:
    """Returns {"files": {relpath: normalized text}, "server_managed": {...}}.

    Applies NORMALIZATION_RULES so an export and a repo ``cxas_app`` that the
    server would treat as the same app compare equal, while every change in
    instructions, code, tools, callbacks, guardrails or model settings still
    shows up.
    """
    raw = _read_tree(root)
    texts: dict[str, str] = {}
    binaries: dict[str, bytes] = {}
    for rel, data in raw.items():
        try:
            texts[rel] = data.decode("utf-8")
        except UnicodeDecodeError:
            binaries[rel] = data

    parsed: dict[str, object] = {}
    for rel, text in texts.items():
        if rel.endswith(".json"):
            try:
                parsed[rel] = json.loads(text)
            except json.JSONDecodeError:
                pass

    # N1: callback file paths.
    renames: dict[str, str] = {}
    for rel, obj in parsed.items():
        if not (rel.startswith("agents/") and isinstance(obj, dict)):
            continue
        agent_dir = rel.rsplit("/", 1)[0]
        for key in CALLBACK_KEYS:
            entries = obj.get(key)
            if not isinstance(entries, list):
                continue
            kind = _snake_callback_kind(key)
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("pythonCode"), str
                ):
                    continue
                old = entry["pythonCode"]
                new = f"{agent_dir}/{kind}/{kind}_{i + 1:02d}/python_code.py"
                entry["pythonCode"] = new
                if old != new:
                    renames[old] = new
    for old, new in renames.items():
        if old in texts and new not in texts:
            texts[new] = texts.pop(old)

    # N2: tool descriptions derived from docstrings.
    for rel, obj in parsed.items():
        if not (rel.startswith("tools/") and isinstance(obj, dict)):
            continue
        pf = obj.get("pythonFunction")
        if not isinstance(pf, dict):
            continue
        code_rel = pf.get("pythonCode")
        func = pf.get("name")
        if isinstance(code_rel, str) and isinstance(func, str) and code_rel in texts:
            doc = _docstring(texts[code_rel], func)
            if doc is not None:
                pf["description"] = doc

    server_managed = {}
    out: dict[str, str] = {}
    for rel in sorted(set(texts) | set(parsed)):
        if rel in parsed:
            obj = parsed[rel]
            if rel == "app.json" and isinstance(obj, dict):
                for key in SERVER_MANAGED_APP_KEYS:  # N5
                    if key in obj:
                        server_managed[key] = obj.pop(key)
            obj = _drop_empty(_sort_sets(obj))  # N3, N4
            if obj in ({}, []):  # N6
                continue
            out[rel] = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        else:
            text = texts[rel].replace("\r\n", "\n").replace("\r", "\n")
            out[rel] = text.rstrip("\n") + "\n"  # N7
    for rel, data in binaries.items():
        out[rel] = "<binary sha256=" + hashlib.sha256(data).hexdigest() + ">\n"
    return {"files": dict(sorted(out.items())), "server_managed": server_managed}


def tree_hash_of_files(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8") + b"\x00")
        h.update(hashlib.sha256(files[rel].encode("utf-8")).digest())
    return h.hexdigest()


def app_tree_hash(root: Path) -> str:
    """sha256 over the *normalized* app tree (equal => same app content)."""
    return tree_hash_of_files(normalize_app_tree(root)["files"])


def raw_tree_hash(root: Path) -> str:
    """sha256 over the raw bytes of the tree (N0 skips only)."""
    h = hashlib.sha256()
    for rel, data in sorted(_read_tree(root).items()):
        h.update(rel.encode("utf-8") + b"\x00")
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def diff_app_trees(
    left_root: Path, right_root: Path, left_label: str, right_label: str
) -> dict:
    """Normalized comparison of two app trees plus the raw file-level view."""
    left = normalize_app_tree(left_root)
    right = normalize_app_tree(right_root)
    lf, rf = left["files"], right["files"]
    only_left = sorted(set(lf) - set(rf))
    only_right = sorted(set(rf) - set(lf))
    differing = sorted(k for k in set(lf) & set(rf) if lf[k] != rf[k])
    diffs = {}
    for rel in sorted(set(differing) | set(only_left) | set(only_right)):
        a = lf.get(rel, "")
        b = rf.get(rel, "")
        diffs[rel] = "".join(
            difflib.unified_diff(
                a.splitlines(keepends=True),
                b.splitlines(keepends=True),
                fromfile=f"{left_label}/{rel}",
                tofile=f"{right_label}/{rel}",
            )
        )
    raw_l, raw_r = _read_tree(left_root), _read_tree(right_root)
    raw_diff = {
        "only_left": sorted(set(raw_l) - set(raw_r)),
        "only_right": sorted(set(raw_r) - set(raw_l)),
        "differing": sorted(
            k for k in set(raw_l) & set(raw_r) if raw_l[k] != raw_r[k]
        ),
    }
    return {
        "left": left_label,
        "right": right_label,
        "identical": not (only_left or only_right or differing),
        "differing_files": differing,
        "only_left": only_left,
        "only_right": only_right,
        "unified_diffs": diffs,
        "server_managed_left": left["server_managed"],
        "server_managed_right": right["server_managed"],
        "left_tree_hash": tree_hash_of_files(lf),
        "right_tree_hash": tree_hash_of_files(rf),
        "raw": raw_diff,
    }


def raw_pretty_diffs(
    left_root: Path, right_root: Path, left_label: str, right_label: str
) -> dict[str, str]:
    """Unified diffs of files that differ *before* normalization.

    Only formatting is unified (JSON with sorted keys, LF endings) so the
    reader sees exactly what rules N1-N6 absorbed. Files present on one side
    only are listed with their full content.
    """
    raw_l, raw_r = _read_tree(left_root), _read_tree(right_root)

    def pretty(rel: str, data: bytes | None) -> str:
        if data is None:
            return ""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "<binary sha256=" + hashlib.sha256(data).hexdigest() + ">\n"
        if rel.endswith(".json"):
            try:
                return json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            except json.JSONDecodeError:
                pass
        return text.replace("\r\n", "\n").rstrip("\n") + "\n"

    out = {}
    for rel in sorted(set(raw_l) | set(raw_r)):
        a, b = raw_l.get(rel), raw_r.get(rel)
        if a == b:
            continue
        out[rel] = "".join(
            difflib.unified_diff(
                pretty(rel, a).splitlines(keepends=True),
                pretty(rel, b).splitlines(keepends=True),
                fromfile=f"{left_label}/{rel}",
                tofile=f"{right_label}/{rel}",
            )
        )
    return out


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=False)
