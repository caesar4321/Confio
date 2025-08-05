#!/usr/bin/env python3
"""
Integration test for Aptos Keyless Bridge
This demonstrates how to use the TypeScript bridge from Python
"""

import asyncio
import subprocess
import time
import sys
from aptos_keyless_client import AptosKeylessClient


async def test_integration():
    """Test the integration between Python and TypeScript bridge"""
    
    print("=== Aptos Keyless Integration Test ===\n")
    
    # Start the TypeScript service
    print("1. Starting TypeScript Keyless Bridge service...")
    process = subprocess.Popen(
        ["npm", "start"],
        cwd="aptos-keyless-bridge",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Give it time to start
    print("   Waiting for service to start...")
    await asyncio.sleep(3)
    
    try:
        # Create client
        client = AptosKeylessClient("http://localhost:3333")
        
        # Test health check
        print("\n2. Testing health check...")
        health = await client.health_check()
        print(f"   Service status: {health['message']}")
        print(f"   Network: {health['network']}")
        
        # Generate ephemeral key pair
        print("\n3. Generating ephemeral key pair...")
        ephemeral_key = await client.generate_ephemeral_key_pair(expiry_hours=24)
        print(f"   Public key: {ephemeral_key.public_key[:32]}...")
        print(f"   Nonce: {ephemeral_key.nonce}")
        print(f"   Expires: {ephemeral_key.expiry_date}")
        
        # Generate OAuth URL
        print("\n4. Generating OAuth URL...")
        oauth_url = await client.generate_oauth_url(
            provider="google",
            client_id="your-google-client-id",
            redirect_uri="http://localhost:3000/callback",
            ephemeral_key_pair=ephemeral_key
        )
        print(f"   OAuth URL generated successfully")
        print(f"   URL: {oauth_url[:80]}...")
        
        print("\n5. Next steps for full integration:")
        print("   a) User clicks the OAuth URL and authenticates")
        print("   b) OAuth provider redirects back with JWT")
        print("   c) Use derive_keyless_account() with the JWT")
        print("   d) Submit transactions with the derived account")
        
        print("\n✅ Integration test successful!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        # Stop the service
        print("\nStopping TypeScript service...")
        process.terminate()
        await asyncio.sleep(1)
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(test_integration())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(0)