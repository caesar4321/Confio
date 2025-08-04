import json
import base64

data = json.load(open("/tmp/zklogin-inputs.json"))

# Reconstruct JWT parts
jwt = "".join(chr(int(x)) for x in data["padded_unsigned_jwt"] if x != "0")
header_b64, payload_b64 = jwt.split(".")

# Decode to check
header_json = base64.b64decode(header_b64 + "=" * (4 - len(header_b64) % 4))
payload_json = base64.b64decode(payload_b64 + "=" * (4 - len(payload_b64) % 4))

print("Header B64 length:", len(header_b64))
print("Payload B64 length:", len(payload_b64))
print("Header JSON:", header_json[:100])
print("Payload JSON:", payload_json[:100])

# Check some indices
print("\nIndices from input:")
print("aud_index_b64:", data.get("aud_index_b64"))
print("aud_value_index:", data.get("aud_value_index"))
print("payload_start_index:", data.get("payload_start_index"))
print("payload_len:", data.get("payload_len"))