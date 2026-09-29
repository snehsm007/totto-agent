"""Totto CXAS test suite.

One command runs everything:

    .venv/bin/python -m totto_suite <command>

Commands: offline | live | snapshot | trend | gate | deploy | backfill |
mutants | verify-ids (see ``python -m totto_suite --help``).

Every run is recorded under ``evals/history/`` (see ``totto_suite.records``)
and tied to the git commit and the CXAS app version it tested.
"""

__version__ = "0.1.0"
