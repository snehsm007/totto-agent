"""argparse front end: ``python -m totto_suite dashboard {build,merge,render,check}``.

Exit codes: 0 ok, 2 bad input / identifier leak (the site must not be
published), 1 never used (the dashboard has no pass/fail of its own).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from totto_suite.dashboard import model, render, scrub

EXIT_OK, EXIT_BAD = 0, 2
COPY_FORWARD = ("voice_comparison.json", "local_history.json", "baseline.json")


def _log(msg: str) -> None:
    print(f"[dashboard] {msg}", flush=True)


def detect_repo_url() -> str | None:
    """https URL of the GitHub repo: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY in
    Actions, else derived from the ``origin`` remote."""
    server, repo = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    if server and repo:
        return f"{server.rstrip('/')}/{repo}"
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"^(?:git@|ssh://git@|https://)(github\.com)[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"https://{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def resolve_data_dir(path: str | None) -> Path | None:
    """Accepts either a data/ dir or a site root that contains data/."""
    if not path:
        return None
    p = Path(path)
    if (p / "data").is_dir():
        return p / "data"
    return p if p.is_dir() else None


def _copy_forward(src_data: Path | None, dst_data: Path) -> None:
    if src_data is None:
        return
    for name in COPY_FORWARD:
        src, dst = src_data / name, dst_data / name
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def _check(site: Path) -> int:
    try:
        scrub.assert_clean(site)
    except scrub.LeakError as err:
        _log(str(err))
        _log("refusing to publish: remove the identifier from the inputs and rebuild")
        return EXIT_BAD
    _log(f"identifier check passed for {site}")
    return EXIT_OK


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)

    gate, gate_error = None, None
    if args.gate_summary:
        if not Path(args.gate_summary).is_file():
            _log(f"gate summary {args.gate_summary} not found; verdict: {args.missing_gate_label!r}")
        else:
            try:
                gate = model.read_json(args.gate_summary)
                if not isinstance(gate, dict):
                    gate, gate_error = None, "gate summary is not a JSON object"
            except model.InputError as err:
                gate_error = str(err)
            if gate_error:
                _log(f"gate summary unreadable: {gate_error}")
    deploy = None
    if args.deploy_record:
        try:
            deploy = model.read_json(args.deploy_record)
        except model.InputError as err:
            _log(f"deploy record unreadable, ignored: {err}")

    latest = model.build_latest(
        gate,
        deploy,
        commit=args.commit,
        run_url=args.run_url,
        missing_gate_label=args.missing_gate_label,
        repo_url=args.repo_url or detect_repo_url(),
        gate_error=gate_error,
    )
    model.write_json(data / "latest.json", latest)

    prev = resolve_data_dir(args.history_dir)
    try:
        runs = model.merge_history(
            model.load_history(prev), model.load_history(data), [model.history_entry(latest)]
        )
    except model.InputError as err:
        _log(f"prior history unreadable: {err}")
        return EXIT_BAD
    model.write_json(data / "history.json", model.history_doc(runs))

    if args.voice_comparison:
        try:
            voice = model.read_json(args.voice_comparison)
        except model.InputError as err:
            _log(f"voice comparison unreadable: {err}")
            return EXIT_BAD
        if voice is not None:
            model.write_json(data / "voice_comparison.json", scrub.relativize(voice))
    if args.local_history:
        try:
            index = model.read_json(args.local_history)
        except model.InputError as err:
            _log(f"local history unreadable: {err}")
            return EXIT_BAD
        rows = model.local_history_rows(index)
        if rows:
            model.write_json(data / "local_history.json", rows)
    _copy_forward(prev, data)

    written = render.render_site(out)
    _log(
        f"built {out}: commit {str(latest.get('commit') or '?')[:12]} verdict {latest['verdict']}"
        f" ({len(runs)} history entries; wrote {', '.join(str(p.relative_to(out)) for p in written)})"
    )
    return _check(out)


def cmd_merge(args: argparse.Namespace) -> int:
    site = Path(args.site)
    data = site / "data"
    prev = resolve_data_dir(args.previous_data)
    try:
        latest = model.read_json(data / "latest.json")
        if not isinstance(latest, dict):
            _log(f"{data / 'latest.json'} missing: build the site first")
            return EXIT_BAD
        runs = model.merge_history(model.load_history(prev), model.load_history(data))
    except model.InputError as err:
        _log(f"unreadable data: {err}")
        return EXIT_BAD
    model.write_json(data / "history.json", model.history_doc(runs))
    _copy_forward(prev, data)

    if args.update_baseline:
        baseline = model.baseline_from_latest(latest)
        if baseline is None:
            _log(
                f"baseline NOT updated: latest verdict is {latest.get('verdict')!r}"
                f" (gate summary present: {bool(latest.get('gate_present'))}); keeping the previous baseline"
            )
        else:
            model.write_json(data / "baseline.json", baseline)
            _log(
                f"baseline updated to commit {str(baseline.get('commit') or '?')[:12]}"
                f" pass rate {baseline.get('pass_rate')}"
            )
    render.render_site(site)
    _log(f"merged {site}: {len(runs)} history entries")
    return _check(site)


def cmd_render(args: argparse.Namespace) -> int:
    try:
        render.render_site(Path(args.site))
    except model.InputError as err:
        _log(str(err))
        return EXIT_BAD
    return _check(Path(args.site))


def cmd_check(args: argparse.Namespace) -> int:
    return _check(Path(args.dir))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m totto_suite dashboard", description=__doc__)
    sub = p.add_subparsers(dest="sub", required=True)

    b = sub.add_parser("build", help="build the static site from CI outputs")
    b.add_argument("--out", required=True, help="output site directory")
    b.add_argument("--gate-summary", help="gate_summary.json from `totto_suite ci-gate`")
    b.add_argument("--deploy-record", help="deploy.json from the deploy-live job")
    b.add_argument("--history-dir", help="previously published site root or its data/ dir")
    b.add_argument("--commit", help="commit SHA shown as 'latest main commit' (default: from gate summary)")
    b.add_argument("--run-url", help="CI run URL (default: from gate summary)")
    b.add_argument(
        "--missing-gate-label",
        default=model.NO_GATE_LABEL,
        help=f"verdict label when there is no gate summary (default {model.NO_GATE_LABEL!r})",
    )
    b.add_argument("--voice-comparison", help="voice A/B table JSON (list of rows)")
    b.add_argument(
        "--local-history",
        help="evals/history/index.json: shown as a clearly labelled 'pre-CI local runs' section",
    )
    b.add_argument("--repo-url", help="https URL of the repo for commit links (default: auto)")
    b.set_defaults(func=cmd_build)

    m = sub.add_parser("merge", help="merge previously published data/ into a site and re-render")
    m.add_argument("--site", required=True)
    m.add_argument("--previous-data", help="data/ dir (or site root) of the previous publish")
    m.add_argument(
        "--update-baseline",
        action="store_true",
        help="write data/baseline.json from this run (only if its verdict is PASS)",
    )
    m.set_defaults(func=cmd_merge)

    r = sub.add_parser("render", help="re-render HTML from site/data/")
    r.add_argument("--site", required=True)
    r.set_defaults(func=cmd_render)

    c = sub.add_parser("check", help="identifier check on a directory (exit 2 on a leak)")
    c.add_argument("dir")
    c.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
