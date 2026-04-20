"""Compatibility entry point for ``python -m r1bt``."""
from prosperity_backtester.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
