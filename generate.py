#!/usr/bin/env python3
"""Launcher so `./generate.py ...` keeps working without an install — it puts
`src/` on sys.path and delegates to the packaged CLI.

Preferred (uv-native): `uv run generate-image ...`  (auto-syncs deps).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from generate_image.cli import main

if __name__ == "__main__":
    main()
