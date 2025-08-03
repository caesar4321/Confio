#!/usr/bin/env python3
"""
Test what format the RPC expects for dry run
"""
import base64
import httpx
import asyncio
import json

async def test_rpc_format():
    """Test RPC format expectations"""
    
    # The transaction bytes from our test
    tx_bytes = bytes.fromhex("00010c1589253999177f7ea3eda6aa412cbaa3238c005ba918e724c0a051fe6d125600f545fa3d180f7938eaa32784b6a25d913a008e0485f1a9c0ae1fc31252dda7de000007084d6f766543616c6c00000f5472616e736665724f626a6563747301000953706c6974436f696e00000a4d65726765436f696e730000075075626c69736800000b4d616b654d6f766556656300000755706772616465000000010120000000000000000000000000000000000000000000000000000000000000000101010100010000")
    
    # Try different formats
    formats = {
        "raw_base64": base64.b64encode(tx_bytes).decode(),
        "raw_hex": tx_bytes.hex(),
        "with_0x": "0x" + tx_bytes.hex()
    }
    
    rpc_url = "https://fullnode.testnet.sui.io"
    
    for format_name, formatted_bytes in formats.items():
        print(f"\nTrying format: {format_name}")
        print(f"Value preview: {formatted_bytes[:50]}...")
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sui_dryRunTransactionBlock",
            "params": [formatted_bytes]
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30.0
            )
            
            result = response.json()
            
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print("Success!")
                print(f"Result: {json.dumps(result.get('result', {}), indent=2)[:200]}...")
                

if __name__ == "__main__":
    asyncio.run(test_rpc_format())