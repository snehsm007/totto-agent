"""Dynamic loader that executes the live callback from $TOTTO_APP_DIR (or repo cxas_app)."""

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5] if "evals" in Path(__file__).parts else Path.cwd()
_APP_DIR = Path(
    os.environ.get("TOTTO_APP_DIR")
    or "<REPO_ROOT>/cxas_app"
)
_SRC = (
    _APP_DIR
    / "agents"
    / "totto_root_agent"
    / "before_agent_callbacks"
    / "init_session_state"
    / "python_code.py"
)
exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), globals())
