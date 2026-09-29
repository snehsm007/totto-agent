"""Public dashboard for the eval-gated CI (milestone M4).

``python -m totto_suite dashboard <subcommand>``:

  build   gate_summary.json (+ deploy.json, prior history) -> static site dir
          (index.html, runs/<key>.html, data/*.json, .nojekyll)
  merge   merge a previously published data/ dir into a site dir, optionally
          move data/baseline.json, re-render and re-check (used by
          scripts/publish_dashboard.sh)
  render  re-render the HTML of a site dir from its data/ files
  check   run the identifier check on any directory (exit 2 on a leak)

The site is served from the orphan-style branch ``dashboard`` (see
scripts/publish_dashboard.sh). index.html is a pure function of the files in
``data/``, so a publish can merge history and re-render without the original
inputs. Everything is stdlib only and uses relative links, so the same tree
works via raw.githack.com and via GitHub Pages (branch ``dashboard``, root).
"""

from totto_suite.dashboard.command import main

__all__ = ["main"]
