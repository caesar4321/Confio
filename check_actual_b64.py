import json
import base64

data = json.load(open("/tmp/zklogin-inputs.json"))
jwt = "".join(chr(int(x)) for x in data["padded_unsigned_jwt"] if x != "0")
header_b64, payload_b64 = jwt.split(".")

# Decode and find positions
payload_decoded = base64.b64decode(payload_b64 + "=" * (4 - len(payload_b64) % 4)).decode()

# Find where "aud" is in the decoded payload
aud_pos = payload_decoded.find('"aud"')
print(f'"aud" position in decoded payload: {aud_pos}')

# Now we need to find where this maps to in the base64
# The circuit likely wants the position where the encoded version of the substring containing "aud" starts

# Let's look at the base64 around that position
# In base64, every 3 bytes becomes 4 characters
# So position 35 in decoded = approximately position 35*4/3 = 46 in base64

estimated_b64_pos = aud_pos * 4 // 3
print(f'Estimated position in base64: {estimated_b64_pos}')
print(f'Base64 substring around that: {payload_b64[max(0,estimated_b64_pos-10):estimated_b64_pos+20]}')

# The circuit actually wants us to find patterns in the base64 itself
# Let's check what patterns exist
print(f'\nBase64 at position 46: {payload_b64[46:56]}')

# Actually, for zkLogin, we might need to look for the encoded pattern differently
# Let's check what the example input.json has
print(f'\nInput aud_index_b64: {data.get("aud_index_b64")}')

# Check if looking for partial matches works
for i in range(len(payload_b64) - 3):
    chunk = payload_b64[i:i+4]
    decoded_chunk = base64.b64decode(chunk + '=' * (4 - len(chunk) % 4))
    if b'aud' in decoded_chunk:
        print(f'Found "aud" pattern at base64 position {i}: {chunk} -> {decoded_chunk}')