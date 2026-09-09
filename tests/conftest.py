import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
t4crte_dir = root_dir / "t4crte"

for d in [str(root_dir), str(t4crte_dir)]:
    if d not in sys.path:
        sys.path.insert(0, d)
