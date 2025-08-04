import json
import base64

data = json.load(open("/tmp/zklogin-inputs.json"))
jwt = "".join(chr(int(x)) for x in data["padded_unsigned_jwt"] if x != "0")
header_b64, payload_b64 = jwt.split(".")

# Check what patterns we should be looking for
fields = ['iss', 'aud', 'sub', 'nonce', 'email_verified']

for field in fields:
    # Try different encodings
    pattern1 = base64.b64encode(field.encode()).decode().rstrip('=')
    pattern2 = base64.b64encode(('"' + field + '"').encode()).decode().rstrip('=')
    pattern3 = base64.b64encode((field + '":').encode()).decode().rstrip('=')
    
    idx1 = payload_b64.find(pattern1)
    idx2 = payload_b64.find(pattern2)
    idx3 = payload_b64.find(pattern3)
    
    print(f"\n{field}:")
    print(f"  As '{field}' -> '{pattern1}' at index: {idx1}")
    print(f"  As '\"{field}\"' -> '{pattern2}' at index: {idx2}")
    print(f"  As '{field}\":' -> '{pattern3}' at index: {idx3}")
    
    # Look for partial matches
    if idx1 == -1 and idx2 == -1 and idx3 == -1:
        # Try to find where it actually appears
        decoded = base64.b64decode(payload_b64 + "=" * (4 - len(payload_b64) % 4)).decode()
        field_pos = decoded.find(field)
        if field_pos != -1:
            # Map back to base64 position (approximate)
            b64_pos_estimate = field_pos * 4 // 3
            print(f"  Field found in decoded at {field_pos}, estimated b64 pos: {b64_pos_estimate}")
            print(f"  B64 at that position: {payload_b64[max(0,b64_pos_estimate-2):b64_pos_estimate+10]}")