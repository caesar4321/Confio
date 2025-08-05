#!/usr/bin/env python3
"""
Simple token deployment using Move source compilation
"""
import asyncio
import subprocess
import tempfile
import os
from pathlib import Path
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.type_tag import StructTag, TypeTag


def compile_move_package(package_path: Path, output_dir: Path):
    """Compile Move package using aptos move command"""
    try:
        # Create a temporary directory for compilation
        cmd = [
            "docker", "run", "--rm", 
            "-v", f"{package_path}:/workspace",
            "-v", f"{output_dir}:/output",
            "aptoslabs/tools:latest",
            "aptos", "move", "compile",
            "--package-dir", "/workspace",
            "--output-dir", "/output"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compilation failed: {result.stderr}")
            return None
        
        print(f"Compilation successful: {result.stdout}")
        return output_dir
        
    except Exception as e:
        print(f"Error compiling package: {e}")
        return None


async def deploy_with_account(account: Account):
    """Deploy tokens using an existing account"""
    
    print(f"Deployer address: {account.address()}")
    
    # Fund account manually using faucet
    print(f"\n=== Account Funding ===")
    print(f"1. Go to: https://aptoslabs.com/testnet-faucet")
    print(f"2. Enter address: {account.address()}")
    print(f"3. Click 'Fund Account' to get testnet APT")
    
    # For now, let's create a simple deployment script that can be run manually
    print("\n=== Manual Deployment Instructions ===")
    print("1. Install Aptos CLI: brew install aptos")
    print("2. Initialize Aptos profile:")
    print(f"   aptos init --profile testnet --network testnet --private-key {account.private_key}")
    print("3. Deploy cUSD:")
    print("   cd contracts/cusd && aptos move publish --profile testnet")
    print("4. Deploy CONFIO:")
    print("   cd contracts/confio && aptos move publish --profile testnet")
    
    print(f"\n=== After Deployment ===")
    print(f"cUSD Token Metadata Address will be: {account.address()}::cusd::get_metadata()")
    print(f"CONFIO Token Metadata Address will be: {account.address()}::confio::get_metadata()")
    print(f"Update blockchain/aptos_balance_service.py with these addresses")


async def main():
    """Main deployment function"""
    
    # Generate a new account for deployment
    deployer = Account.generate()
    
    print("=== Aptos Token Deployment ===")
    print(f"Generated deployer account: {deployer.address()}")
    print(f"Private key: {deployer.private_key}")
    print("Save this private key securely!")
    
    await deploy_with_account(deployer)


if __name__ == "__main__":
    asyncio.run(main())