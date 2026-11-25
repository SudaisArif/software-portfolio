#!/usr/bin/env python3
"""Generate the latest target allocation CSV without treating it as an order ticket."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_research import main


if __name__ == "__main__":
    main()
