import json

data = json.load(open("/tmp/zklogin-inputs.json"))

# Check numeric values that might be out of range
print("Checking numeric values:")
print(f"all_inputs_hash: {data.get('all_inputs_hash')}")
print(f"  Length: {len(data.get('all_inputs_hash', ''))}")

print(f"jwt_randomness: {data.get('jwt_randomness')}")
print(f"  Length: {len(data.get('jwt_randomness', ''))}")

print(f"salt: {data.get('salt')}")
print(f"  Length: {len(data.get('salt', ''))}")

print(f"max_epoch: {data.get('max_epoch')}")

# Check if any index is negative or too large
print("\nChecking indices:")
for key in data:
    if 'index' in key or 'colon' in key or 'length' in key or 'value_index' in key:
        val = data[key]
        if isinstance(val, str) and val.lstrip('-').isdigit():
            num_val = int(val)
            if num_val < 0 or num_val > 10000:
                print(f"  {key}: {val} (POTENTIAL ISSUE!)")
            else:
                print(f"  {key}: {val}")

# Check array lengths
print("\nChecking array lengths:")
for key in ['ext_aud', 'ext_nonce', 'ext_kc', 'ext_ev', 'padded_unsigned_jwt', 'signature', 'modulus']:
    if key in data:
        print(f"  {key}: {len(data[key])} elements")