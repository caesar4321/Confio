#!/usr/bin/env python3
"""
Deploy cUSD and CONFIO tokens to Aptos testnet using Python SDK
"""
import asyncio
import os
from pathlib import Path
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.package_publisher import PackagePublisher
from aptos_sdk.transactions import EntryFunction, TransactionArgument
from aptos_sdk.type_tag import StructTag, TypeTag


async def deploy_tokens():
    """Deploy cUSD and CONFIO tokens to Aptos testnet"""
    
    # Initialize client for testnet
    client = RestClient("https://api.testnet.aptoslabs.com/v1")
    
    # Create or load deployer account
    # In production, you'd load from a secure key file
    deployer = Account.generate()
    print(f"Deployer address: {deployer.address()}")
    
    # Fund the account for testnet deployment
    await client.fund_account(deployer.address(), 100_000_000)  # 1 APT
    print("Account funded for deployment")
    
    # Deploy cUSD contract
    print("\n=== Deploying cUSD Token ===")
    cusd_package_path = Path("contracts/cusd")
    
    try:
        # Create package publisher
        publisher = PackagePublisher(client, deployer)
        
        # Compile and publish cUSD package
        cusd_result = await publisher.publish_package(cusd_package_path)
        print(f"cUSD deployed at: {cusd_result}")
        
        # Get the metadata address for cUSD
        cusd_metadata_address = f"{deployer.address()}::cusd::CUSD"
        print(f"cUSD metadata: {cusd_metadata_address}")
        
    except Exception as e:
        print(f"Error deploying cUSD: {e}")
    
    # Deploy CONFIO contract
    print("\n=== Deploying CONFIO Token ===")
    confio_package_path = Path("contracts/confio")
    
    try:
        # Compile and publish CONFIO package
        confio_result = await publisher.publish_package(confio_package_path)
        print(f"CONFIO deployed at: {confio_result}")
        
        # Get the metadata address for CONFIO
        confio_metadata_address = f"{deployer.address()}::confio::CONFIO"
        print(f"CONFIO metadata: {confio_metadata_address}")
        
    except Exception as e:
        print(f"Error deploying CONFIO: {e}")
    
    print(f"\n=== Deployment Summary ===")
    print(f"Deployer Address: {deployer.address()}")
    print(f"Private Key (save this!): {deployer.private_key}")
    print(f"Network: Aptos Testnet")
    print(f"cUSD Token Address: {deployer.address()}::cusd")
    print(f"CONFIO Token Address: {deployer.address()}::confio")
    
    # Close client
    await client.close()


if __name__ == "__main__":
    asyncio.run(deploy_tokens())