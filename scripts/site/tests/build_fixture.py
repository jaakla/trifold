"""Synthetic UI-only fixture: one mixed L12 cell, three runs, no global arrays."""
import importlib.util
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('settlement_build', root / 'settlementcheck/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
sys.path.insert(0, str(root / 'landcheck/python'))
from _fastloc import locate_index

writer = build.RunWriter(12)
index = locate_index(24.7536, 59.4370, 12)
writer.add(0, index, 11)
writer.add(index, 1, 30, True, .6, True)
writer.add(index + 1, 20 * 4**12 - index - 1, 11)
build.write_dataset(Path(sys.argv[1]) / 'degurba_R2025A_E2025_L12.tfdg', writer, '00' * 32)
