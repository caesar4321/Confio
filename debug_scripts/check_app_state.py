
import os
import base64
from algosdk.v2client import algod

# Testnet algod
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""

def check_app_state(app_id):
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    try:
        app_info = client.application_info(app_id)
        global_state = app_info['params']['global-state']
        
        print(f"Global State for App {app_id}:")
        for key_value in global_state:
            key_b64 = key_value['key']
            key = base64.b64decode(key_b64).decode('utf-8', errors='ignore')
            value = key_value['value']
            
            val_str = ""
            if value['type'] == 1: # bytes
                val_b64 = value['bytes']
                val_bytes = base64.b64decode(val_b64)
                try:
                    val_addr =  val_bytes.hex() # encoding.encode_address(val_bytes) requires 32 bytes
                    # Try to encode as address if length is 32
                    if len(val_bytes) == 32:
                        from algosdk import encoding
                        val_addr = encoding.encode_address(val_bytes)
                    val_str = f"{val_addr} (b64: {val_b64})"
                except:
                    val_str = f"{val_bytes} (b64: {val_b64})"
            else:
                val_str = str(value['uint'])
                
            print(f"  {key}: {val_str}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_app_state(744368177)
