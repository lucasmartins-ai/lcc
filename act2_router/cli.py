"""Backwards-compatibility re-export for lcc.router.cli."""

from lcc.router.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
