#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
violations = sorted(p.name for p in ROOT.glob('test_*.py') if p.is_file())

if violations:
    print('ERROR: root-level test_*.py files are not allowed.')
    print('Move them under tests/ (unit/integration) or ops/diagnostics/ (manual scripts).')
    for name in violations:
        print(f' - {name}')
    sys.exit(1)

print('OK: no root-level test_*.py files found.')
