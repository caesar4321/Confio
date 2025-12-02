import os
import sys
from dotenv import load_dotenv

# Load .env.testnet
load_dotenv('.env.testnet')

# Override App ID
os.environ['ALGORAND_PAYROLL_APP_ID'] = '750527129'

# Add path
sys.path.append(os.getcwd())

# Import and run script
from contracts.payroll.setup_delegates import main

if __name__ == "__main__":
    main()
