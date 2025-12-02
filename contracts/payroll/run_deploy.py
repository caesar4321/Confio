import os
import sys
from dotenv import load_dotenv

# Load .env.testnet
load_dotenv('.env.testnet')

# Add path
sys.path.append(os.getcwd())

# Import and run deploy script
from contracts.payroll.deploy_payroll import main

if __name__ == "__main__":
    main()
