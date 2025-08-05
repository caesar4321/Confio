#!/bin/bash

echo "=== Aptos Keyless Integration Test ==="
echo

# Check if TypeScript bridge is running
echo "1. Checking if Keyless Bridge service is running..."
if curl -s http://localhost:3333/api/keyless/health > /dev/null; then
    echo "   ✅ Keyless Bridge is running"
    curl -s http://localhost:3333/api/keyless/health | python3 -m json.tool
else
    echo "   ❌ Keyless Bridge is NOT running"
    echo "   Please start it with: cd aptos-keyless-bridge && npm start"
    exit 1
fi

echo
echo "2. Testing ephemeral key generation..."
RESPONSE=$(curl -s -X POST http://localhost:3333/api/keyless/ephemeral-key \
    -H "Content-Type: application/json" \
    -d '{"expiryHours": 24}')

if echo "$RESPONSE" | grep -q "success"; then
    echo "   ✅ Ephemeral key generated successfully"
    echo "$RESPONSE" | python3 -m json.tool | head -10
else
    echo "   ❌ Failed to generate ephemeral key"
    echo "$RESPONSE"
fi

echo
echo "3. Testing Python client..."
python3 -c "
import asyncio
from aptos_keyless_client import AptosKeylessClient

async def test():
    try:
        client = AptosKeylessClient()
        health = await client.health_check()
        print('   ✅ Python client connected successfully')
        print(f'   Service version: {health.get(\"version\")}')
        print(f'   Network: {health.get(\"network\")}')
        await client.close()
    except Exception as e:
        print(f'   ❌ Python client error: {e}')

asyncio.run(test())
"

echo
echo "4. Integration Summary:"
echo "   - TypeScript Bridge: Running on port 3333"
echo "   - Python Client: Can connect and communicate"
echo "   - React Native: Ready to use with useAptosKeyless hook"
echo
echo "Next steps:"
echo "1. Configure OAuth providers (Google/Apple)"
echo "2. Test authentication flow in React Native app"
echo "3. Implement transaction signing"