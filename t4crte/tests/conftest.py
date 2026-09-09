import sys
from pathlib import Path

tests_dir = Path(__file__).resolve().parent
t4crte_dir = tests_dir.parent
root_dir = t4crte_dir.parent

for d in [str(t4crte_dir), str(root_dir)]:
    if d not in sys.path:
        sys.path.insert(0, d)
