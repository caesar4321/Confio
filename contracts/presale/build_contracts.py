#!/usr/bin/env python3
"""
Build script for CONFIO Presale contract.
Compiles PyTeal to TEAL (approval + clear) for deployment.

Note: Deployment and app opt-ins are handled by deploy_presale.py.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from confio_presale import compile_presale


def build():
    teal = compile_presale()
    print("# Presale Approval Program (TEAL)")
    print(teal)
    print("\n# Clear Program (always approve)")
    print("#pragma version 8\nint 1")


if __name__ == "__main__":
    build()

