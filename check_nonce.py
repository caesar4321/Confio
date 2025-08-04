import json

with open('/tmp/zklogin-inputs-v2.json', 'r') as f:
    data = json.load(f)

# Decode ext_nonce
nonce_chars = []
for code in data.get('ext_nonce', []):
    if code != '0':
        nonce_chars.append(chr(int(code)))
    else:
        break

nonce = ''.join(nonce_chars)
print(f"Nonce value: {nonce}")
print(f"Nonce length: {len(nonce)}")

# Check other values
print(f"\next_aud_length: {data.get('ext_aud_length')}")
print(f"ext_nonce_length: {data.get('ext_nonce_length')}")
print(f"ext_kc_length: {data.get('ext_kc_length')}")

# Check if nonce is base64
import base64
try:
    decoded = base64.b64decode(nonce + '=' * (4 - len(nonce) % 4))
    print(f"Nonce decoded from base64: {decoded.hex()[:40]}...")
    print(f"Decoded length: {len(decoded)} bytes")
except:
    print("Nonce is not base64")

# Check expected nonce format for zkLogin
print(f"\nzkLogin expects nonce to be 27 bytes (20 bytes hash + padding)")
print(f"Current nonce appears to be: {len(nonce)} characters")