import json
data = json.load(open("/tmp/zklogin-inputs.json"))
jwt = "".join(chr(int(x)) for x in data["padded_unsigned_jwt"] if x != "0")
print("JWT length:", len(jwt))
print("First 100 chars:", jwt[:100])
print("Has dot:", "." in jwt)
parts = jwt.split(".")
if len(parts) >= 2:
    print("Header length:", len(parts[0]))
    print("Payload length:", len(parts[1]))