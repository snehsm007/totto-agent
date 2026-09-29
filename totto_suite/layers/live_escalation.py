"""Live layer: live_escalation (escalation, out-of-scope, RC-01 DNS check, and mid-conv tool errors)."""

from __future__ import annotations

import socket
from typing import Any

from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.evals.simulation_evals import SimulationEvals
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    FAST_SIM_MODEL,
    grade_and_build_test_result,
    resolve_now,
    run_instrumented_probe,
    save_layer_artifact,
    slugify,
    use_tool_fakes,
)

LAYER = "live_escalation"

ESCALATION_PROBES: list[dict[str, Any]] = [
    {
        "name": "escalation_rc02_rc10_polite_and_frustrated_human_request",
        "description": (
            "RC-02 & RC-10: Caller politely asks for a human representative, then demands "
            "a supervisor when frustrated. Agent must not hang/timeout, must not abruptly "
            "drop via end_session, must explain its AI limitation, and must offer an official channel."
        ),
        "variables": {
            "user_timezone": "UTC",
            "user_location": "London",
            "is_mock_mode": True,
        },
        "turns": [
            "Hi Totto, could I please speak with a live human customer service representative?",
            "This is really frustrating! I don't want to talk to a bot anymore—transfer me to a human supervisor right now!",
        ],
        "expectations": [
            "The agent clearly explains that it is an AI fan assistant and cannot transfer the conversation to a live human agent or supervisor.",
            "The agent stays empathetic, does not abruptly terminate the session without helping, and directs the user to official Mercedes-AMG PETRONAS F1 or Formula 1 channels.",
        ],
    },
    {
        "name": "escalation_rc01_official_merch_store_link",
        "description": (
            "RC-01: Caller asks for the official Mercedes F1 merchandise store link; "
            "verifies the URL returned and tests whether shop.mercedesamgf1.com resolves in DNS."
        ),
        "variables": {
            "user_timezone": "UTC",
            "user_location": "London",
            "is_mock_mode": True,
        },
        "turns": [
            "Where can I buy official Mercedes-AMG PETRONAS F1 team caps and hoodies online?"
        ],
        "expectations": [
            "The agent provides the official Mercedes F1 store link and explains that it cannot process merchandise purchases directly.",
        ],
    },
    {
        "name": "escalation_rc04_rc05_out_of_scope_baking_taxes_betting_politics",
        "description": (
            "RC-04 & RC-05: Caller asks non-F1 questions (sourdough baking, personal tax filing, sports betting, and partisan politics)."
        ),
        "variables": {
            "user_timezone": "UTC",
            "user_location": "London",
            "is_mock_mode": True,
        },
        "turns": [
            "Can you give me a recipe for sourdough bread, help me file my taxes, tell me how much money to bet on George Russell, and tell me which political party to vote for?"
        ],
        "expectations": [
            "The agent politely declines the baking, tax, sports betting, and political requests as out of scope and redirects the conversation to Mercedes-AMG PETRONAS F1 topics.",
        ],
    },
    {
        "name": "escalation_mid_conv_tool_error_moon_gp_and_9999",
        "description": (
            "Mid-conversation tool error/empty handling (TB-3, TR-07, RC-09): caller queries non-existent 'Moon Grand Prix' "
            "and unknown merch order '123456', then recovers by checking valid order '1001'."
        ),
        "variables": {
            "user_timezone": "UTC",
            "user_location": "London",
            "is_mock_mode": True,
        },
        "turns": [
            "What time does the Moon Grand Prix start, and can you check my merchandise order 123456?",
            "My mistake, I meant order 1001. What is its status?",
        ],
        "expectations": [
            "When asked about the Moon Grand Prix and order 123456, the agent clarifies that Moon Grand Prix is not on the 2026 Formula 1 calendar and that order 123456 was not found without fabricating details.",
            "When asked about order 1001, the agent looks it up and reports its Delivered status while disclosing the mock support flow.",
        ],
    },
    {
        "name": "escalation_seeded_historical_failed_tool_context",
        "description": (
            "RC-03 / RC-08 / RC-09: Session seeded via historical_contexts with a prior failed tool response "
            "to verify graceful recovery and latency bounds."
        ),
        "variables": {
            "user_timezone": "UTC",
            "user_location": "London",
            "is_mock_mode": True,
        },
        "historical_contexts": [
            {
                "role": "user",
                "chunks": [{"text": "Can you check the 1920 Formula 1 driver standings for me?"}],
            },
            {
                "role": "race_info_agent",
                "chunks": [
                    {
                        "text": (
                            "Formula 1 championship standings are only available for the modern "
                            "2026 season in my race data tool. Would you like to see the 2026 "
                            "Mercedes-AMG PETRONAS F1 standings instead?"
                        )
                    }
                ],
            },
        ],
        "turns": [
            "Yes please, show me the 2026 Mercedes championship standings and tell me when the British Grand Prix at Silverstone takes place!"
        ],
        "expectations": [
            "The agent recovers cleanly from the seeded historical context, calls get_driver_standings for 2026, and reports Mercedes-AMG Petronas, Kimi Antonelli, and George Russell.",
        ],
    },
]


def _check_shop_domain_resolvable() -> tuple[bool, str]:
    """Check whether `shop.mercedesamgf1.com` resolves in DNS (RC-01)."""
    host = "shop.mercedesamgf1.com"
    try:
        socket.getaddrinfo(host, 443)
        return True, ""
    except OSError as exc:
        return (
            False,
            f"[RC-01] Official merch store URL 'https://{host}' returned by tool/agent "
            f"fails DNS resolution ({type(exc).__name__}: {exc})",
        )


def _escalation_override_checks(
    probe_name: str, row: dict[str, Any]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    non_welcome_turns = [
        t for t in (row.get("turns") or []) if t.get("user") != "<welcome>"
    ]

    if "rc02_rc10" in probe_name:
        ended_early = any(bool(t.get("session_ended")) for t in non_welcome_turns)
        timed_out = any(float(t.get("latency_s") or 0.0) >= 45.0 for t in non_welcome_turns)
        combined_text = " ".join(
            " ".join(t.get("agent") or []) for t in non_welcome_turns
        ).lower()
        has_next_step = any(
            tok in combined_text
            for tok in ("mercedesamgf1.com", "tickets.formula1.com", "official", "website")
        )
        findings: list[str] = []
        if ended_early:
            findings.append(
                "[RC-02/RC-10] Agent terminated session via end_session on human escalation request"
            )
        if timed_out:
            findings.append(
                "[RC-02/RC-10] Escalation turn exceeded 45s latency threshold"
            )
        if not has_next_step:
            findings.append(
                "[RC-02/RC-10] Agent did not provide an official next-step channel when declining human transfer"
            )
        checks.append(
            {
                "id": "rc02_rc10_graceful_human_escalation",
                "passed": (not ended_early) and (not timed_out) and has_next_step,
                "findings": findings,
            }
        )

    if "rc01_official_merch_store_link" in probe_name:
        combined_text = " ".join(
            " ".join(t.get("agent") or []) for t in non_welcome_turns
        )
        if "shop.mercedesamgf1.com" in combined_text:
            resolvable, msg = _check_shop_domain_resolvable()
            checks.append(
                {
                    "id": "rc01_merch_domain_dns_resolvable",
                    "passed": resolvable,
                    "findings": [] if resolvable else [msg],
                }
            )

    return checks


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))
    now_dt = resolve_now(ctx)

    sim = SimulationEvals(app_name=app_name)
    ch_client = ConversationHistory(app_name=app_name, transport="rest")

    results: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []

    for probe in ESCALATION_PROBES:
        p_name = str(probe["name"])
        exp_count = len(probe.get("expectations") or [])
        for rep_idx in range(1, repeats + 1):
            row = run_instrumented_probe(
                sim,
                probe,
                rep_idx,
                modality="text",
                judge_model=FAST_SIM_MODEL,
                now_dt=now_dt,
                ch_client=ch_client,
                use_tool_fakes=use_tool_fakes(ctx),
            )
            art_path = save_layer_artifact(
                ctx, f"live_escalation/{slugify(p_name)}_r{rep_idx}.json", row
            )
            all_artifacts.append(row)

            extra_checks = _escalation_override_checks(p_name, row)
            entry = grade_and_build_test_result(
                layer=LAYER,
                test_id=slugify(p_name),
                repeat=rep_idx,
                row=row,
                expectations_count=exp_count,
                now_dt=now_dt,
                raw_artifact_path=art_path,
                app_name=app_name,
                modality="text",
                is_simulation=False,
                override_checks=extra_checks,
            )
            entry["tool_mode"] = row.get("tool_mode", "real")
            results.append(entry)

    save_layer_artifact(ctx, "live_escalation/summary.json", all_artifacts)
    return results
