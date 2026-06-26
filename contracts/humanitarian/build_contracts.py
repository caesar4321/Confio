#!/usr/bin/env python3
"""Compile the PuyaPy humanitarian aid contract.

Requires PuyaPy/Algorand Python tooling in the active environment:

    python3.12 -m pip install puyapy
    python3.12 contracts/humanitarian/build_contracts.py
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'ayuda_humanitaria.py'
OUT_DIR = ROOT / 'artifacts'


def main() -> int:
    if sys.version_info < (3, 12):
        print('PuyaPy requires Python 3.12 or newer. Use a separate compiler venv from the Django Python 3.10 venv.', file=sys.stderr)
        return 2
    OUT_DIR.mkdir(exist_ok=True)
    cmd = [
        sys.executable,
        '-m',
        'puyapy',
        str(SOURCE),
        '--out-dir',
        str(OUT_DIR),
    ]
    return subprocess.call(cmd)


if __name__ == '__main__':
    raise SystemExit(main())
