"""Ramps test package.

This file is load-bearing: without it Django's test runner does not treat
`ramps/tests/` as a package, and `manage.py test ramps` silently discovers
ZERO tests — every file in here (Koywe limits, document types, sync,
Guardarian autoswap, ramp owner-only) was being skipped in aggregate runs
while passing when named explicitly.
"""
