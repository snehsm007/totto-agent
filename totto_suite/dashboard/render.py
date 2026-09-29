"""Static HTML rendering of a dashboard site from its ``data/`` files.

Self-contained pages: inline CSS and inline SVG, no JavaScript, no external
assets, relative links only (works on raw.githack.com and GitHub Pages).
Rendering is deterministic (no clock reads) so re-publishing unchanged data
produces an identical git tree.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from totto_suite.dashboard import model

CSS = """
:root{--pass:#1a7f37;--fail:#cf222e;--inc:#9a6700;--none:#57606a;--bg:#f6f8fa;--fg:#1f2328;
--line:#d0d7de}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);
background:#fff}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:19px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.sub{color:var(--none);margin:0 0 16px}
.banner{border:2px solid var(--none);border-radius:10px;padding:16px 20px;background:var(--bg)}
.banner.PASS{border-color:var(--pass)}.banner.FAIL{border-color:var(--fail)}
.banner.INCONCLUSIVE{border-color:var(--inc)}
.verdict{display:inline-block;font-weight:700;font-size:22px;padding:2px 12px;border-radius:6px;
color:#fff;background:var(--none)}
.verdict.PASS{background:var(--pass)}.verdict.FAIL{background:var(--fail)}
.verdict.INCONCLUSIVE{background:var(--inc)}
.sha{font:600 17px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:12px 0 0}
dl.kv dt{color:var(--none)}dl.kv dd{margin:0}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--bg)}td.num{text-align:right;font-variant-numeric:tabular-nums}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.pill{display:inline-block;padding:0 6px;border-radius:4px;color:#fff;background:var(--none);
font-size:12px;font-weight:600}
.pill.PASS{background:var(--pass)}.pill.FAIL{background:var(--fail)}
.pill.INCONCLUSIVE,.pill.FLAKY,.pill.INFRA_ERROR{background:var(--inc)}
.note{background:#fff8c5;border:1px solid #d4a72c;border-radius:6px;padding:8px 12px}
footer{margin-top:40px;color:var(--none);font-size:13px}
svg text{font:11px system-ui,sans-serif;fill:var(--none)}
"""


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def pct(rate: Any) -> str:
    r = model.as_rate(rate)
    return "n/a" if r is None else f"{r * 100:.1f}%"


def verdict_class(v: Any) -> str:
    s = str(v or "")
    return s if s in model.GATE_VERDICTS else "NONE"


def pill(v: Any) -> str:
    s = str(v or "UNKNOWN")
    cls = s if s in ("PASS", "FAIL", "INCONCLUSIVE", "FLAKY", "INFRA_ERROR") else "NONE"
    return f'<span class="pill {cls}">{e(s)}</span>'


def commit_link(sha: Any, repo_url: Any, short: bool = False) -> str:
    if not sha:
        return "<em>unknown</em>"
    text = str(sha)[:7] if short else str(sha)
    if repo_url:
        return f'<a class="mono" href="{e(repo_url)}/commit/{e(sha)}">{e(text)}</a>'
    return f'<span class="mono">{e(text)}</span>'


def link(url: Any, text: str | None = None) -> str:
    if not url:
        return "<em>n/a</em>"
    return f'<a href="{e(url)}">{e(text or url)}</a>'


def page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(title)}</title><style>{CSS}</style></head>\n"
        f"<body><main>\n{body}\n</main></body></html>\n"
    )


def trend_svg(runs: list[dict], width: int = 760, height: int = 220) -> str:
    """Inline SVG line chart of pass rate (and baseline) over gated runs."""
    pts = [r for r in runs if model.as_rate(r.get("pass_rate")) is not None]
    if not pts:
        return (
            '<p class="note">No gated runs yet. The chart fills in after the first gated'
            " run on <code>main</code>.</p>"
        )
    left, right, top, bottom = 44, 12, 12, 28
    w, h = width - left - right, height - top - bottom
    n = len(pts)

    def x(i: int) -> float:
        return left + (w / 2 if n == 1 else w * i / (n - 1))

    def y(rate: float) -> float:
        return top + h * (1 - rate)

    parts = [
        f'<svg role="img" aria-label="pass rate trend" viewBox="0 0 {width} {height}"'
        f' width="100%" style="max-width:{width}px" xmlns="http://www.w3.org/2000/svg">'
    ]
    for g in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{left}" x2="{left + w}" y1="{y(g):.1f}" y2="{y(g):.1f}"'
            ' stroke="#d0d7de" stroke-width="1"/>'
            f'<text x="{left - 6}" y="{y(g) + 4:.1f}" text-anchor="end">{int(g * 100)}%</text>'
        )
    base = [
        (x(i), y(model.as_rate(r.get("baseline_pass_rate"))))
        for i, r in enumerate(pts)
        if model.as_rate(r.get("baseline_pass_rate")) is not None
    ]
    if len(base) > 1:
        parts.append(
            '<polyline fill="none" stroke="#57606a" stroke-dasharray="4 3" stroke-width="1.5" points="'
            + " ".join(f"{a:.1f},{b:.1f}" for a, b in base)
            + '"/>'
        )
    if n > 1:
        parts.append(
            '<polyline fill="none" stroke="#0969da" stroke-width="2" points="'
            + " ".join(f"{x(i):.1f},{y(model.as_rate(r['pass_rate'])):.1f}" for i, r in enumerate(pts))
            + '"/>'
        )
    colors = {"PASS": "#1a7f37", "FAIL": "#cf222e", "INCONCLUSIVE": "#9a6700"}
    for i, r in enumerate(pts):
        rate = model.as_rate(r["pass_rate"])
        c = colors.get(str(r.get("verdict")), "#57606a")
        tip = f"{str(r.get('commit') or '?')[:7]} {r.get('verdict')} {rate * 100:.1f}%"
        parts.append(
            f'<circle cx="{x(i):.1f}" cy="{y(rate):.1f}" r="4" fill="{c}"><title>{e(tip)}</title></circle>'
        )
    def day(r: dict) -> str:
        return e(str(r.get("finished_at") or r.get("generated_at") or "")[:10])

    parts.append(
        f'<text x="{left}" y="{height - 8}">{day(pts[0])}</text>'
        f'<text x="{left + w}" y="{height - 8}" text-anchor="end">{day(pts[-1])}</text>'
        "</svg>"
    )
    parts.append(
        '<p class="sub">Blue: gate pass rate per gated <code>main</code> run (dot colour = verdict).'
        " Dashed grey: the baseline the gate compared against.</p>"
    )
    return "".join(parts)


def tests_table(tests: list[dict]) -> str:
    if not tests:
        return "<p><em>No per-test results in this run.</em></p>"
    rows = []
    for t in tests:
        ids = "<br>".join(f"<code>{e(p)}</code>" for p in t.get("platform_ids") or []) or "—"
        reps = " ".join(pill(s) for s in t.get("repeats") or [])
        fv = t.get("fake_verified")
        mode = e(t.get("tool_mode") or "")
        if fv is not None:
            mode += f" ({'fake verified' if fv else 'fake NOT verified'})"
        msg = f"<br><small>{e(t['message'])}</small>" if t.get("message") else ""
        rows.append(
            f"<tr><td><code>{e(t.get('id'))}</code>{msg}</td><td>{e(t.get('layer') or '')}</td>"
            f"<td>{pill(t.get('status'))}</td><td>{reps or '—'}</td><td>{mode or '—'}</td><td>{ids}</td></tr>"
        )
    return (
        "<table><tr><th>test</th><th>layer</th><th>verdict</th><th>repeats</th>"
        "<th>tool mode</th><th>platform IDs (app-relative)</th></tr>" + "".join(rows) + "</table>"
    )


def layers_table(layers: dict) -> str:
    if not layers:
        return ""
    rows = "".join(
        f"<tr><td>{e(n)}</td><td class=num>{e(s.get('pass'))}</td><td class=num>{e(s.get('fail'))}</td>"
        f"<td class=num>{e(s.get('infra_error'))}</td><td class=num>{e(s.get('skipped'))}</td>"
        f"<td class=num>{pct(s.get('pass_rate'))}</td></tr>"
        for n, s in sorted(layers.items())
    )
    return (
        "<table><tr><th>layer</th><th>pass</th><th>fail</th><th>infra error</th><th>skipped</th>"
        f"<th>pass rate</th></tr>{rows}</table>"
    )


def summary_kv(latest: dict) -> str:
    dep = latest.get("deploy") or {}
    version = dep.get("version")
    if version and dep.get("version_display_name"):
        version_html = f"<code>{e(version)}</code> ({e(dep['version_display_name'])})"
    elif version:
        version_html = f"<code>{e(version)}</code>"
    else:
        version_html = "<em>no live deploy recorded for this commit</em>"
    status = dep.get("status")
    if status and str(status).upper() != "SUCCESS":
        step = f" at step {e(dep['failed_step'])}" if dep.get("failed_step") else ""
        version_html += f" — live deploy {pill(str(status).upper())}{step}"
    fv = latest.get("fake_verified")
    mode = e(latest.get("tool_mode") or "n/a")
    if fv is not None:
        mode += " (fake results verified)" if fv else " (fake results NOT verified)"
    passed = (
        f" ({latest['tests_passed']}/{latest['tests_total']} tests)" if latest.get("tests_total") else ""
    )
    items = [
        ("Gate pass rate", f"{pct(latest.get('pass_rate'))}{passed}"),
        ("Baseline (last green main)", pct(latest.get("baseline_pass_rate"))),
        ("Tool mode", mode),
        ("Gate target", e(latest.get("target") or "n/a")),
        ("CI run", link(latest.get("run_url"))),
        ("Gate finished", e(latest.get("finished_at") or "n/a")),
        ("Dashboard built", e(latest.get("generated_at"))),
        ("CXAS version on live", version_html),
    ]
    if dep.get("phone_deployments"):
        items.append(
            ("Phone deployment", " ".join(f"<code>{e(p)}</code>" for p in dep["phone_deployments"]))
        )
    if latest.get("reasons"):
        items.append(("Gate reasons", "<br>".join(e(r) for r in latest["reasons"])))
    if latest.get("gate_error"):
        items.append(("Gate summary error", e(latest["gate_error"])))
    return '<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in items) + "</dl>"


def history_table(runs: list[dict], repo_url: Any) -> str:
    if not runs:
        return "<p><em>No history yet.</em></p>"
    rows = []
    for r in reversed(runs):
        detail = link(r["detail_page"], "details") if r.get("detail_page") else "—"
        tests = f"{r.get('tests_passed')}/{r.get('tests_total')}" if r.get("tests_total") else "—"
        rows.append(
            f"<tr><td>{e(r.get('finished_at') or r.get('generated_at'))}</td>"
            f"<td>{commit_link(r.get('commit'), repo_url, short=True)}</td><td>{pill(r.get('verdict'))}</td>"
            f"<td class=num>{pct(r.get('pass_rate'))}</td><td class=num>{pct(r.get('baseline_pass_rate'))}</td>"
            f"<td class=num>{tests}</td><td>{e(r.get('tool_mode') or '—')}</td>"
            f"<td>{e(r.get('cxas_version_display_name') or r.get('cxas_version') or '—')}</td>"
            f"<td>{link(r.get('run_url'), 'run') if r.get('run_url') else '—'}</td><td>{detail}</td></tr>"
        )
    return (
        "<table><tr><th>time (UTC)</th><th>commit</th><th>verdict</th><th>pass rate</th><th>baseline</th>"
        "<th>tests</th><th>tool mode</th><th>live version</th><th>CI run</th><th>details</th></tr>"
        + "".join(rows)
        + "</table>"
    )


VOICE_COLUMNS = (
    "model",
    "run_id",
    "pass_rate",
    "passed",
    "total",
    "median_turn_latency_s",
    "p90_turn_latency_s",
    "notes",
)


def voice_table(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    body = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        cells = []
        for c in VOICE_COLUMNS:
            v = r.get(c)
            if c == "pass_rate":
                cells.append(f"<td class=num>{pct(v)}</td>")
            elif c in ("median_turn_latency_s", "p90_turn_latency_s"):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    text = f"{float(v):.2f} s"
                else:
                    text = "n/a" if v is None else str(v)
                cells.append(f"<td class=num>{e(text)}</td>")
            elif c == "run_id":
                cells.append(f"<td><code>{e(v)}</code></td>")
            else:
                cells.append(f"<td>{e(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<h2>Voice model comparison</h2>"
        '<p class="sub">From real staging platform runs (<code>data/voice_comparison.json</code>).</p>'
        "<table><tr><th>model</th><th>run ID</th><th>pass rate</th><th>passed</th><th>total</th>"
        "<th>median turn latency</th><th>p90 turn latency</th><th>notes</th></tr>"
        + "".join(body)
        + "</table>"
    )


def local_history_section(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    body = "".join(
        f"<tr><td>{e(r.get('point_time'))}</td><td><code>{e(r.get('run_id'))}</code></td>"
        f"<td>{e(r.get('mode'))}{' (imported)' if r.get('imported') else ''}</td>"
        f"<td class=mono>{e(r.get('agent_commit') or '—')}{' (dirty)' if r.get('agent_dirty') else ''}</td>"
        f"<td class=num>{e(r.get('passed'))}/{e(r.get('decided'))}</td><td>{e(r.get('model') or '')}</td>"
        f"<td><small>{e(r.get('rationale') or '')}</small></td></tr>"
        for r in reversed(rows)
        if isinstance(r, dict)
    )
    return (
        "<h2>Pre-CI local runs (not gate results)</h2>"
        '<p class="note">These rows were recorded on a developer machine <strong>before</strong> the CI'
        " gate existed (offline suites, manual live runs and snapshots from"
        " <code>evals/history/</code>). They are not CI gate results, and their commits may not"
        " exist on <code>origin/main</code>.</p>"
        f"<details><summary>{len(rows)} local runs</summary>"
        "<table><tr><th>time (UTC)</th><th>run</th><th>mode</th><th>agent commit</th><th>passed</th>"
        f"<th>model</th><th>rationale</th></tr>{body}</table></details>"
    )


def render_index(latest: dict, runs: list[dict], voice: Any, local_rows: Any, baseline: Any) -> str:
    repo_url = latest.get("repo_url")
    v = latest.get("verdict")
    no_gate = "" if latest.get("gate_present") else (
        '<p class="note">No gate result is available for this commit, so none is shown. The'
        " verdict above is a status label, not a test result.</p>"
    )
    detail = (
        f'<p>{link(latest["detail_page"], "Per-test details for this run")}</p>'
        if latest.get("detail_page")
        else ""
    )
    base_html = ""
    if isinstance(baseline, dict):
        base_html = (
            f"<p>Current gate baseline: {pct(baseline.get('pass_rate'))} from commit "
            f"{commit_link(baseline.get('commit'), repo_url, short=True)} "
            f"(set {e(baseline.get('baseline_set_at'))}; <a href=\"data/baseline.json\">baseline.json</a>).</p>"
        )
    body = f"""
<h1>Totto CI dashboard</h1>
<p class="sub">Eval-gated delivery of the Totto CXAS agent. Updated automatically by GitHub Actions
after every gated run on <code>main</code>.</p>
<section class="banner {verdict_class(v)}">
<div>Latest <code>main</code> commit</div>
<div class="sha">{commit_link(latest.get('commit'), repo_url)}</div>
<div style="margin-top:8px">Gate result: <span class="verdict {verdict_class(v)}">{e(v)}</span></div>
{summary_kv(latest)}
</section>
{no_gate}
{detail}
<h2>Trend</h2>
{trend_svg(runs)}
{base_html}
{history_table(runs, repo_url)}
<h2>Latest run: tests</h2>
{layers_table(latest.get('layers') or {})}
{tests_table(latest.get('tests') or [])}
{voice_table(voice)}
{local_history_section(local_rows)}
<footer>
Data: <a href="data/latest.json">latest.json</a> · <a href="data/history.json">history.json</a>.
Built by <code>python -m totto_suite dashboard build</code> and published to the <code>dashboard</code>
branch by <code>scripts/publish_dashboard.sh</code>. Platform IDs are app-relative on purpose
(no project or app IDs are published).
</footer>"""
    return page(f"Totto CI dashboard — {str(latest.get('commit') or '')[:7]} {v}", body)


def render_run(latest: dict) -> str:
    repo_url = latest.get("repo_url")
    v = latest.get("verdict")
    body = f"""
<p><a href="../index.html">← dashboard</a></p>
<h1>Gate run <code>{e(latest.get('run_id') or latest.get('key'))}</code></h1>
<section class="banner {verdict_class(v)}">
<div>Commit</div><div class="sha">{commit_link(latest.get('commit'), repo_url)}</div>
<div style="margin-top:8px">Gate result: <span class="verdict {verdict_class(v)}">{e(v)}</span></div>
{summary_kv(latest)}
</section>
<h2>Layers</h2>
{layers_table(latest.get('layers') or {}) or '<p><em>No layer summary.</em></p>'}
<h2>Tests</h2>
{tests_table(latest.get('tests') or [])}
"""
    return page(f"Gate run {latest.get('run_id') or latest.get('key')} — {v}", body)


def render_site(site: Path) -> list[Path]:
    """(Re)writes index.html (+ this run's detail page) from site/data/."""
    site = Path(site)
    data = site / "data"
    latest = model.read_json(data / "latest.json")
    if not isinstance(latest, dict):
        raise model.InputError("data/latest.json missing or not an object")
    runs = model.load_history(data)
    voice = model.read_json(data / "voice_comparison.json")
    local_rows = model.read_json(data / "local_history.json")
    baseline = model.read_json(data / "baseline.json")
    written = []
    idx = site / "index.html"
    idx.write_text(render_index(latest, runs, voice, local_rows, baseline), encoding="utf-8")
    written.append(idx)
    if latest.get("detail_page"):
        run_page = site / latest["detail_page"]
        run_page.parent.mkdir(parents=True, exist_ok=True)
        run_page.write_text(render_run(latest), encoding="utf-8")
        written.append(run_page)
    nojekyll = site / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.write_text("", encoding="utf-8")
    return written
