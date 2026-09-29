"""Gate rule for the staging CXAS eval gate (pure functions, unit-tested).

1. Repeats -> one status per test (:func:`aggregate_repeats`):
   only *decided* repeats count (PASS/FAIL; INFRA_ERROR and SKIPPED are not
   agent verdicts). PASS iff passes > fails (strict majority, ties FAIL). With
   the default 2 repeats this means "every decided repeat passed"; with 3 a
   single flaky repeat is out-voted. No decided repeat -> INFRA_ERROR (or
   SKIPPED if every repeat was skipped).
2. Rates: pass_rate = PASS / (PASS + FAIL) over aggregated tests, overall
   and per layer.
3. Checks (:func:`evaluate`), all must hold:
   * overall pass rate >= ``overall_floor``; each layer's pass rate >= its
     ``layer_floors`` entry (floors come from measured staging runs, see
     ``gate_thresholds.json``);
   * with a baseline of the same tool_mode: overall pass rate >=
     baseline - ``baseline_tolerance_pp``/100, and at most
     ``max_new_failures`` tests that PASSed in the baseline now FAIL.
4. Verdict with infra errors (429/503/504/QUOTA_EXHAUSTED/deadline are
   INFRA_ERROR, never FAIL):
   * no decided test at all -> INCONCLUSIVE;
   * checks fail even if every INFRA_ERROR test had passed -> FAIL (infra
     could not have changed the outcome);
   * infra share > ``max_infra_ratio`` and the checks would fail if every
     INFRA_ERROR test had failed -> INCONCLUSIVE (re-run);
   * otherwise checks on decided tests decide PASS/FAIL.
"""

from __future__ import annotations

from typing import Any

PASS, FAIL, INFRA, SKIPPED = "PASS", "FAIL", "INFRA_ERROR", "SKIPPED"
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")
EXIT_CODES = {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 3}

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "aggregation": "strict majority of decided repeats (ties FAIL; INFRA_ERROR/SKIPPED repeats ignored)",
    "overall_floor": 0.0,
    "layer_floors": {},
    "baseline_tolerance_pp": 10.0,
    "max_new_failures": 1,
    "max_infra_ratio": 0.25,
}


def aggregate_status(statuses: list[str]) -> str:
    passes = sum(1 for s in statuses if s == PASS)
    fails = sum(1 for s in statuses if s == FAIL)
    if passes + fails == 0:
        if statuses and all(s == SKIPPED for s in statuses):
            return SKIPPED
        return INFRA
    return PASS if passes > fails else FAIL


def aggregate_repeats(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups per-repeat results by test id (keeps first-seen order)."""
    order: list[str] = []
    by_id: dict[str, list[dict[str, Any]]] = {}
    for t in tests:
        tid = str(t.get("id"))
        if tid not in by_id:
            by_id[tid] = []
            order.append(tid)
        by_id[tid].append(t)
    out = []
    for tid in order:
        reps = sorted(by_id[tid], key=lambda r: int(r.get("repeat") or 1))
        statuses = [str(r.get("status")) for r in reps]
        modes = {str(r.get("tool_mode") or "real") for r in reps}
        verdicts = [r.get("fake_verified") for r in reps]
        if any(v is False for v in verdicts):
            fv: bool | None = False
        elif any(v is True for v in verdicts):
            fv = True
        else:
            fv = None
        out.append(
            {
                "id": tid,
                "layer": reps[0].get("layer"),
                "status": aggregate_status(statuses),
                "repeat_statuses": statuses,
                "tool_mode": modes.pop() if len(modes) == 1 else "mixed",
                "fake_verified": fv,
                "repeats": reps,
            }
        )
    return out


def counts(agg: list[dict[str, Any]], layer: str | None = None) -> dict[str, int]:
    c = {PASS: 0, FAIL: 0, INFRA: 0, SKIPPED: 0}
    for t in agg:
        if layer is not None and t.get("layer") != layer:
            continue
        c[t["status"]] = c.get(t["status"], 0) + 1
    return c


def rate(passes: int, fails: int) -> float | None:
    return round(passes / (passes + fails), 4) if passes + fails else None


def _check_rates(
    layer_counts: dict[str, dict[str, int]],
    overall: dict[str, int],
    thresholds: dict[str, Any],
    baseline_rate: float | None,
    infra_as: str | None,
) -> list[str]:
    """Floor/baseline checks; infra_as=PASS/FAIL treats INFRA as that, None ignores it."""

    def eff(c: dict[str, int]) -> tuple[int, int]:
        p, f = c.get(PASS, 0), c.get(FAIL, 0)
        if infra_as == PASS:
            p += c.get(INFRA, 0)
        elif infra_as == FAIL:
            f += c.get(INFRA, 0)
        return p, f

    problems = []
    p, f = eff(overall)
    overall_rate = rate(p, f)
    floor = float(thresholds.get("overall_floor") or 0.0)
    if overall_rate is not None and overall_rate < floor:
        problems.append(f"overall pass rate {overall_rate:.1%} < floor {floor:.1%}")
    for layer, lfloor in sorted((thresholds.get("layer_floors") or {}).items()):
        if layer not in layer_counts:
            continue
        lp, lf = eff(layer_counts[layer])
        lrate = rate(lp, lf)
        if lrate is not None and lrate < float(lfloor):
            problems.append(f"{layer} pass rate {lrate:.1%} < floor {float(lfloor):.1%}")
    if baseline_rate is not None and overall_rate is not None:
        tol = float(thresholds.get("baseline_tolerance_pp") or 0.0) / 100.0
        if overall_rate < baseline_rate - tol - 1e-9:
            problems.append(
                f"overall pass rate {overall_rate:.1%} < baseline {baseline_rate:.1%} "
                f"- {tol * 100:.0f}pp"
            )
    return problems


def new_failures(agg: list[dict[str, Any]], baseline_tests: list[dict[str, Any]]) -> list[str]:
    """Test ids that PASSed in the baseline and are a decided FAIL now."""
    base = {str(t.get("id")): t.get("status") for t in baseline_tests or []}
    return sorted(t["id"] for t in agg if t["status"] == FAIL and base.get(t["id"]) == PASS)


def evaluate(
    agg: list[dict[str, Any]],
    thresholds: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    tool_mode: str | None = None,
) -> dict[str, Any]:
    """Applies the gate rule; returns verdict, reasons, rates and counts."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    overall = counts(agg)
    layers = sorted({str(t.get("layer")) for t in agg})
    layer_counts = {layer: counts(agg, layer) for layer in layers}
    pass_rate = rate(overall[PASS], overall[FAIL])
    reasons: list[str] = []

    baseline_rate: float | None = None
    baseline_tests: list[dict[str, Any]] = []
    baseline_note = "no baseline: absolute floors only"
    if baseline:
        b_mode = baseline.get("tool_mode")
        if tool_mode and b_mode and b_mode != tool_mode:
            baseline_note = (
                f"baseline ignored: its tool_mode={b_mode} differs from this run's {tool_mode}"
            )
        else:
            raw = baseline.get("pass_rate")
            baseline_rate = float(raw) if raw is not None else None
            baseline_tests = list(baseline.get("tests") or [])
            baseline_note = f"baseline run {baseline.get('run_id')} ({baseline.get('commit')})"
    reasons.append(baseline_note)

    regressions = new_failures(agg, baseline_tests) if baseline_tests else []
    max_new = int(th.get("max_new_failures") or 0)
    regression_problem = (
        [f"{len(regressions)} test(s) passed in baseline but fail now (max {max_new}): "
         + ", ".join(regressions)]
        if len(regressions) > max_new
        else []
    )

    decided_total = overall[PASS] + overall[FAIL]
    infra_total = overall[INFRA]
    judged = decided_total + infra_total
    infra_ratio = round(infra_total / judged, 4) if judged else 0.0

    if decided_total == 0:
        verdict = "INCONCLUSIVE"
        reasons.append(f"no decided tests ({infra_total} INFRA_ERROR)")
    else:
        optimistic = _check_rates(layer_counts, overall, th, baseline_rate, PASS)
        pessimistic = _check_rates(layer_counts, overall, th, baseline_rate, FAIL)
        decided = _check_rates(layer_counts, overall, th, baseline_rate, None)
        if optimistic or regression_problem:
            verdict = "FAIL"
            reasons.extend(regression_problem + optimistic)
        elif infra_ratio > float(th["max_infra_ratio"]) and pessimistic:
            verdict = "INCONCLUSIVE"
            reasons.append(
                f"INFRA_ERROR share {infra_ratio:.0%} > {float(th['max_infra_ratio']):.0%} "
                "and could flip the result: " + "; ".join(pessimistic)
            )
        elif decided:
            verdict = "FAIL"
            reasons.extend(decided)
        else:
            verdict = "PASS"
            reasons.append("all floors met" + ("" if baseline_rate is None else " and no regression vs baseline"))
        if regressions and not regression_problem:
            reasons.append(f"tolerated new failures vs baseline: {', '.join(regressions)}")

    return {
        "verdict": verdict,
        "exit_code": EXIT_CODES[verdict],
        "reasons": reasons,
        "pass_rate": pass_rate,
        "baseline_pass_rate": baseline_rate,
        "infra_ratio": infra_ratio,
        "counts": overall,
        "layers": {
            layer: {
                "pass": c[PASS],
                "fail": c[FAIL],
                "infra_error": c[INFRA],
                "skipped": c[SKIPPED],
                "pass_rate": rate(c[PASS], c[FAIL]),
            }
            for layer, c in layer_counts.items()
        },
        "new_failures_vs_baseline": regressions,
        "thresholds": th,
    }
