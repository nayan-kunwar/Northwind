"""One-command entry point: python run.py"""

from __future__ import annotations

import sys

from northwind.cli import main

if __name__ == "__main__":
    sys.exit(main())
