#!/usr/bin/env python3
"""Shared code and prompt bundler for Totto, Mercedes F1 Fan Agent.

Synchronizes shared prompt fragments from `lib/shared_prompts/*.txt` into
`cxas_app/agents/**/instruction.txt` and validates bundle consistency.
"""

import argparse
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_PROMPTS_DIR = PROJECT_ROOT / "lib" / "shared_prompts"
AGENTS_DIR = PROJECT_ROOT / "cxas_app" / "agents"


def sync_shared_prompts(check_only: bool = False) -> bool:
    """Sync `lib/shared_prompts/persona.txt` into `totto_root_agent/instruction.txt` if present."""
    if not SHARED_PROMPTS_DIR.exists():
        return True

    persona_file = SHARED_PROMPTS_DIR / "persona.txt"
    root_inst = AGENTS_DIR / "totto_root_agent" / "instruction.txt"
    if not persona_file.exists() or not root_inst.exists():
        return True

    persona_block = persona_file.read_text(encoding="utf-8").strip()
    if not persona_block.startswith("<persona>") or not persona_block.endswith("</persona>"):
        return True

    inst_text = root_inst.read_text(encoding="utf-8")
    pattern = re.compile(r"<persona>.*?</persona>", re.DOTALL)
    if not pattern.search(inst_text):
        return True

    updated_text = pattern.sub(persona_block, inst_text, count=1)
    if updated_text != inst_text:
        if check_only:
            print(
                "[BUNDLE CHECK] Drift detected between lib/shared_prompts/persona.txt "
                "and cxas_app/agents/totto_root_agent/instruction.txt"
            )
            return False
        root_inst.write_text(updated_text, encoding="utf-8")
        print("[BUNDLE] Synchronized <persona> into totto_root_agent/instruction.txt")
    else:
        print("[BUNDLE] Shared prompts are in sync with cxas_app/")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle shared prompts and imports into cxas_app/.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that cxas_app/ is in sync with lib/ without modifying files.",
    )
    args = parser.parse_args()
    ok = sync_shared_prompts(check_only=args.check)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
