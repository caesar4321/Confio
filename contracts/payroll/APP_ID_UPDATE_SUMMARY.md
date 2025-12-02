# Payroll App ID Update Summary

## Final App ID: `750525296`

This document confirms all locations where the payroll app ID has been updated.

## Updated Files

### 1. Django Settings (Python code default)
**File**: `/Users/julian/Confio/config/settings.py:520`

```python
'ALGORAND_PAYROLL_APP_ID': config('ALGORAND_PAYROLL_APP_ID', default=750525296, cast=int),
```

✅ **Status**: Updated to `750525296`

### 2. Environment Variables (Testnet)
**File**: `/Users/julian/Confio/.env.testnet:19`

```bash
ALGORAND_PAYROLL_APP_ID=750525296
```

✅ **Status**: Updated to `750525296`

### 3. Deployment Scripts
**File**: `/Users/julian/Confio/contracts/payroll/setup_delegates.py:18`

```python
APP_ID = int(os.getenv("ALGORAND_PAYROLL_APP_ID", "750525296"))
```

✅ **Status**: Updated to `750525296`

**File**: `/Users/julian/Confio/contracts/verify_deployment_simple.py:13`

```python
APP_ID = 750525296
```

✅ **Status**: Updated to `750525296`

## Verification

Run this command to verify:

```bash
grep -r "PAYROLL_APP_ID.*750" /Users/julian/Confio \
  --include="*.py" --include=".env*" \
  --exclude-dir=myvenv --exclude-dir=node_modules \
  | grep -v "\.pyc"
```

Expected output:
- `config/settings.py` → `750525296`
- `.env.testnet` → `750525296`
- `contracts/payroll/setup_delegates.py` → `750525296`
- `contracts/verify_deployment_simple.py` → `750525296`

## App ID History

| App ID      | Status      | Notes                                    |
|-------------|-------------|------------------------------------------|
| 750067819   | ❌ Deprecated | Vault key bug + no withdrawals          |
| 750524790   | ❌ Deprecated | Fixed vault key but no withdrawals      |
| **750525296** | ✅ **ACTIVE** | **Vault key fixed + withdrawals added** |

## How Django Loads the App ID

Django uses this priority order:

1. **Environment variable** (highest priority)
   - Reads from `ALGORAND_PAYROLL_APP_ID` in environment
   - Set via `.env.testnet` for testnet

2. **Default in settings.py** (fallback)
   - If env var not set, uses default `750525296`
   - Defined in `config/settings.py`

## To Apply Changes

### If Django server is running:

```bash
# 1. Stop the server (Ctrl+C)

# 2. Restart with correct env
make runserver

# Or manually:
export CONFIO_ENV=testnet
source .env.testnet
python manage.py runserver
```

### Verify it's using the correct app ID:

```bash
# Django shell
python manage.py shell

>>> from django.conf import settings
>>> settings.ALGORAND_PAYROLL_APP_ID
750525296  # Should show this!
```

## Mobile App

The mobile app reads the app ID from the GraphQL backend, which reads from Django settings.

**No mobile app changes needed** - just restart the Django server.

## Summary

✅ All files updated to use app ID `750525296`
✅ Both code defaults and environment variables set
✅ Contract has withdrawal functions
✅ Delegates configured
✅ Ready for production use

**Action Required**: Restart Django server to pick up new .env.testnet values!
