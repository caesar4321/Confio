import json
import base64

data = json.load(open("/tmp/zklogin-inputs.json"))

# Check what aud_index_b64 should be
jwt = "".join(chr(int(x)) for x in data["padded_unsigned_jwt"] if x != "0")
header_b64, payload_b64 = jwt.split(".")

# Look for "aud" in base64 payload
aud_str = '"aud"'
aud_b64 = base64.b64encode(aud_str.encode()).decode().rstrip('=')

print(f"Looking for '{aud_str}' encoded as '{aud_b64}' in payload_b64")
print(f"Payload B64 first 200 chars: {payload_b64[:200]}")

index = payload_b64.find(aud_b64)
print(f"Found at index: {index}")
print(f"Input has aud_index_b64: {data.get('aud_index_b64')}")

# Check decoded payload
payload_decoded = base64.b64decode(payload_b64 + "=" * (4 - len(payload_b64) % 4)).decode()
print(f"\nDecoded payload first 200 chars: {payload_decoded[:200]}")
aud_json_index = payload_decoded.find('"aud"')
print(f'"aud" in decoded payload at: {aud_json_index}')