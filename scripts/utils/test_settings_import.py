import os
import sys

# Set environment variable to ensure correct settings loading
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['CONFIO_ENV'] = 'testnet'
os.environ['ALGORAND_NETWORK'] = 'testnet'

print("Attempting to import config.settings...", file=sys.stderr)
try:
    import config.settings
    print("Successfully imported config.settings", file=sys.stderr)
    print(f"ALGORAND_CONFIO_ASSET_ID: {getattr(config.settings, 'ALGORAND_CONFIO_ASSET_ID', 'NOT FOUND')}", file=sys.stderr)
except Exception as e:
    print(f"Failed to import config.settings: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
