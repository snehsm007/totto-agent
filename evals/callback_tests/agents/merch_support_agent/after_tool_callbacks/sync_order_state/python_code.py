"""Dynamic loader that executes the live callback from $TOTTO_APP_DIR (or repo cxas_app)."""

import os
from pathlib import Path

_APP_DIR = Path(
    os.environ.get("TOTTO_APP_DIR")
    or "<REPO_ROOT>/cxas_app"
)
_SRC = (
    _APP_DIR
    / "agents"
    / "merch_support_agent"
    / "after_tool_callbacks"
    / "sync_order_state"
    / "python_code.py"
)
exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), globals())
