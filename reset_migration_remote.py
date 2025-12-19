from users.models import User, Account

def reset_user(identifier, mode='username'):
    try:
        if mode == 'username':
            user = User.objects.get(username=identifier)
            accounts = Account.objects.filter(user=user, account_type='personal')
        elif mode == 'address':
            accounts = Account.objects.filter(algorand_address=identifier)
        
        if not accounts.exists():
            print(f"[{identifier}] No accounts found.")
            return

        for acc in accounts:
            print(f"[{identifier}] Found Account {acc.id} (Addr: {acc.algorand_address})")
            print(f"  - Current Status: {acc.is_keyless_migrated}")
            
            if acc.is_keyless_migrated:
                acc.is_keyless_migrated = False
                acc.save()
                print(f"  - UPDATED to False ✅")
            else:
                print(f"  - Already False (Skipped)")

    except User.DoesNotExist:
        print(f"[{identifier}] User not found.")
    except Exception as e:
        print(f"[{identifier}] Error: {e}")

print("--- Resetting Migration Status on EC2 ---")

# Reset manuelconfio
reset_user('manuelconfio', mode='username')

# Reset luisg (By V2 Address)
LUISG_V2 = "BLELALXEWR4LPM452TPCNM7EWU5R7AGCBHK65HEWHQQU66GLSY2YXC4LLU"
reset_user(LUISG_V2, mode='address')

print("--- Done ---")
