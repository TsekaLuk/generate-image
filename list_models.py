#!/usr/bin/env python3
"""Launcher for the provider/model list — prefer `uv run generate-image-models`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from generate_image.list_models import main

if __name__ == "__main__":
    main()
