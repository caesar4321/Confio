#!/usr/bin/env python3
"""
Build script for the CONFIO rewards vault.

Compiles the PyTeal approval program and writes the TEAL output
to stdout. Use this to regenerate `approval.teal` after contract
updates.
"""

from contracts.rewards.confio_rewards import compile_confio_rewards


def build():
    teal = compile_confio_rewards()
    print("# Rewards Approval Program (TEAL)")
    print(teal)
    print("\n# Clear Program (always approve)")
    print("#pragma version 8\nint 1")


if __name__ == "__main__":
    build()
