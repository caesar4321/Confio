#!/usr/bin/env python3
import json
import base64

with open('/tmp/zklogin-inputs-v3.json', 'r') as f:
    data = json.load(f)

# Extract JWT from padded array
jwt_chars = []
for code in data.get('padded_unsigned_jwt', []):
    if code != '0':
        jwt_chars.append(chr(int(code)))
    else:
        break

jwt = ''.join(jwt_chars)
print(f"JWT length: {len(jwt)}")

# Parse JWT
header_b64, payload_b64 = jwt.split('.')[:2]
payload = base64.b64decode(payload_b64 + '=' * (4 - len(payload_b64) % 4)).decode()
payload_json = json.loads(payload)

print(f"JWT nonce: {payload_json.get('nonce')}")
print(f"JWT nonce length: {len(payload_json.get('nonce', ''))}")

# Check ext_nonce
ext_nonce_chars = []
for code in data.get('ext_nonce', []):
    if code != '0':
        ext_nonce_chars.append(chr(int(code)))

ext_nonce = ''.join(ext_nonce_chars)
print(f"\next_nonce: {ext_nonce}")
print(f"ext_nonce length: {len(ext_nonce)}")
print(f"ext_nonce_length field: {data.get('ext_nonce_length')}")

# Check problematic fields
print(f"\nnonce_length_b64: {data.get('nonce_length_b64')} (should be ~37 for 27-char nonce)")
print(f"nonce_value_index: {data.get('nonce_value_index')}")
print(f"nonce_index_b64: {data.get('nonce_index_b64')}")

# The problem
print("\n⚠️ ISSUE: nonce_length_b64 is calculated for JWT's 64-char nonce")
print("but ext_nonce uses the 27-char original nonce")
print("This mismatch causes circuit validation to fail")