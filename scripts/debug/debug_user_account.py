from users.models import User, Account

def check_user():
    # ... (finding user code remains) ...
    users = User.objects.filter(username__icontains='julian')
    print(f"Found {users.count()} users matching 'julian'.")
    
    target_user = None
    for u in users:
        print(f"  User: {u.id} | {u.username} | {u.email} | {u.first_name} {u.last_name}")
        if u.username == 'julianmoonluna' or 'moon' in u.last_name.lower():
            target_user = u
            
    if not target_user:
        print("Target user not found explicitly.")
        target_user = User.objects.first() # Fallback

    print(f"\n--- Testing Account Lookup for User {target_user.id} ---")
    
    # Simulate Personal Context
    acct = Account.objects.filter(
        user=target_user,
        account_type='personal',
        account_index=0,
        deleted_at__isnull=True
    ).first()
    
    if acct:
        print(f"Personal Account: {acct} (Address: {acct.algorand_address})")
    else:
        print("Personal Account: NOT FOUND")

    # Now run the WS simulation with THIS user
    print("\n--- Running WS Flow ---")
    import asyncio
    from debug_ws_flow import MockConsumer
    
    consumer = MockConsumer(target_user)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Use real invoice ID VH7VFLWT
    try:
        loop.run_until_complete(consumer._create_prepare_pack(
            amount=0.10, 
            asset_type='CONFIO', 
            internal_id='VH7VFLWT'
        ))
    except Exception as e:
         print(f"WS Flow Crash: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    check_user()
check_user()
