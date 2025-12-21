import asyncio
from payments.ws_consumers import PaySessionConsumer, _DummyRequest, _DummyInfo
from blockchain.payment_mutations import CreateSponsoredPaymentMutation
from users.models import User
from decimal import Decimal

# Mock the consumer environment
class MockConsumer:
    def __init__(self, user):
        self.scope = {'user': user}
        self._raw_token = "mock_token"

    async def _create_prepare_pack(self, amount, asset_type, internal_id=None, note=None, recipient_business_id=None):
        # Generate a real token for the user
        from rest_framework_simplejwt.tokens import RefreshToken
        user = self.scope.get('user')
        refresh = RefreshToken.for_user(user)
        self._raw_token = str(refresh.access_token)
        
        # Build a fake Authorization header so jwt_context utils work
        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        if recipient_business_id:
            meta["HTTP_X_RECIPIENT_BUSINESS_ID"] = str(recipient_business_id)

        user = self.scope.get("user")
        dummy_request = _DummyRequest(user=user, meta=meta)
        info = _DummyInfo(context=dummy_request)

        from channels.db import database_sync_to_async
        # Wrap the sync mutation call
        @database_sync_to_async
        def run_mutation():
            return CreateSponsoredPaymentMutation.mutate(
                None,
                info,
                amount=amount,
                asset_type=asset_type,
                internal_id=internal_id,
                note=note,
                create_receipt=False,
            )

        print(f"Calling Mutation with internal_id={internal_id}, amount={amount}...")
        try:
            result = await run_mutation()
            
            success = getattr(result, "success", False)
            error = getattr(result, "error", None)
            print(f"Mutation returned: Success={success}, Error={error}")
            return {
                "success": success,
                "error": error
            }
        except Exception as e:
            print(f"Mutation RAISED Exception: {e}")
            return {"success": False, "error": str(e)}

def debug_ws_flow():
    # Use the invoice ID from user report
    inv_id = 'VH7VFLWT' 
    # Need a payer user - let's pick one
    payer = User.objects.first()
    print(f"Using payer: {payer}")
    
    consumer = MockConsumer(payer)
    
    # Run the async method
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Mimic the payload sent by PaymentProcessingScreen
    # amount=0.10, asset_type='CONFIO', internal_id='VH7VFLWT'
    loop.run_until_complete(consumer._create_prepare_pack(
        amount=0.10, 
        asset_type='CONFIO', 
        internal_id=inv_id
    ))
    loop.close()

if __name__ == '__main__':
    debug_ws_flow()
debug_ws_flow()
