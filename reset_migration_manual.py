import os
import django
import sys

# Setup Django environment
import sys
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Confio.settings') # Try 'Confio.settings' or 'confio_project.settings' depending on structure
# Checking structure: /Users/julian/Confio/manage.py exists? Yes. 
# Usually manage.py has the correct settings module. Let's check manage.py content first if this fails, but usually it's 'Confio.settings' or similar.
# Let's try to infer from 'manage.py' by viewing it first, OR just run via 'python manage.py shell' which handles setup automatically.

# BETTER APPROACH: Run via manage.py shell command input.
# But script is easier. Let's try running via 'python manage.py shell < script.py' pattern.


from users.models import User, UserAccount

def reset_user(identifier, mode='username'):
    try:
        if mode == 'username':
            user = User.objects.get(username=identifier)
            # Assuming UserAccount is linked or we check specific account
            # Usually strict mapping. Let's find valid personal account.
            accounts = UserAccount.objects.filter(user=user, account_type='personal')
        elif mode == 'address':
            # Identify by V2 address
            accounts = UserAccount.objects.filter(algorand_address=identifier)
        
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

if __name__ == "__main__":
    print("--- Resetting Migration Status ---")
    
    # Reset manuelconfio
    reset_user('manuelconfio', mode='username')
    
    # Reset luisg (By V2 Address)
    LUISG_V2 = "BLELALXEWR4LPM452TPCNM7EWU5R7AGCBHK65HEWHQQU66GLSY2YXC4LLU"
    reset_user(LUISG_V2, mode='address')
    
    print("--- Done ---")
