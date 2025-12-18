# Clean Option B implementation snippet
# This will be integrated into payment_mutations.py

def rebuild_sponsor_transactions_option_b(signed_transactions, internal_id, settings, logger):
    """
    Option B: Rebuild sponsor transactions deterministically from user-signed AXFERs.
    
    Returns: (success, error, signed_txn_objects) tuple
    """
    import base64
    import msgpack
    from algosdk import encoding, transaction
    from algosdk.transaction import SuggestedParams
    from algosdk.abi import ABIType, Method, Argument, Returns
    from blockchain.kms_manager import get_kms_signer_from_settings
    
    try:
        # Step 1: Decode and validate user transactions
        user_txn1_bytes = base64.b64decode(signed_transactions[0])
        user_txn2_bytes = base64.b64decode(signed_transactions[1])
        
        user_txn1_dict = msgpack.unpackb(user_txn1_bytes, raw=False)
        user_txn2_dict = msgpack.unpackb(user_txn2_bytes, raw=False)
        
        # Extract inner transaction data
        txn1 = user_txn1_dict.get('txn', {})
        txn2 = user_txn2_dict.get('txn', {})
        
        # Verify group IDs match
        grp1 = txn1.get('grp')
        grp2 = txn2.get('grp')
        
        if not grp1 or not grp2:
            return False, "User transactions missing group ID", None
        
        if grp1 != grp2:
            return False, "User transactions have different group IDs", None
        
        group_id_bytes = grp1
        
        # Step 2: Extract ALL parameters from user transactions
        # These MUST be reused exactly to rebuild the same group
        user_first = txn1.get('fv')
        user_last = txn1.get('lv')
        user_gh = txn1.get('gh')
        user_gen = txn1.get('gen', b'')  # Can be empty
        
        # Verify fees are 0 (sponsor covers all fees)
        fee1 = txn1.get('fee', 0)
        fee2 = txn2.get('fee', 0)
        
        if fee1 != 0 or fee2 != 0:
            logger.warning(f"User transactions have non-zero fees: {fee1}, {fee2}")
        
        # Extract addresses and amounts
        payer_address = encoding.encode_address(txn1.get('snd'))
        merchant_address = encoding.encode_address(txn1.get('arcv'))
        fee_recipient_address = encoding.encode_address(txn2.get('arcv'))
        asset_id = txn1.get('xaid')
        
        # Verify both AXFERs have same sender
        if encoding.encode_address(txn2.get('snd')) != payer_address:
            return False, "User transactions have different senders", None
        
        logger.info(f"Rebuilding with: payer={payer_address[:10]}..., merchant={merchant_address[:10]}..., asset={asset_id}")
        logger.info(f"User params: fv={user_first}, lv={user_last}, fee1={fee1}, fee2={fee2}")
        
        # Step 3: Get sponsor configuration
        from blockchain.payment_transaction_builder import PaymentTransactionBuilder
        builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
        
        signer = get_kms_signer_from_settings()
        signer.assert_matches_address(builder.sponsor_address)
        sponsor_address = builder.sponsor_address
        
        # Step 4: Rebuild sponsor transactions with EXACT user parameters
        # Create SuggestedParams from user transaction data
        params = SuggestedParams(
            fee=1000,  # Will be overridden per transaction
            first=user_first,
            last=user_last,
            gh=user_gh,
            gen=user_gen if isinstance(user_gen, str) else user_gen.decode('utf-8') if user_gen else '',
            flat_fee=True
        )
        
        # Build sponsor payment (index 0) - covers fees for the group
        sponsor_payment = transaction.PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=payer_address,
            amt=0,  # No MBR topup in deterministic rebuild
            note=None  # No note to match original
        )
        sponsor_payment.fee = 3000  # Fixed sponsor payment fee
        sponsor_payment.group = group_id_bytes
        
        # Determine method for app call
        if asset_id == builder.cusd_asset_id:
            method_name = "pay_with_cusd"
        elif asset_id == builder.confio_asset_id:
            method_name = "pay_with_confio"
        else:
            return False, f'Unknown asset ID: {asset_id}', None
        
        # Build ABI method
        method = Method(
            name=method_name,
            args=[
                Argument(arg_type="address", name="recipient"),
                Argument(arg_type="string", name="internal_id")
            ],
            returns=Returns(arg_type="void")
        )
        
        # ABI encode arguments - must match exactly what was used during creation
        string_type = ABIType.from_string("string")
        recipient_arg = encoding.decode_address(merchant_address)
        
        # Use empty string for internal_id in deterministic rebuild (matches creation when no receipt)
        internal_id_arg = string_type.encode("")
        
        # Build sponsor app call (index 3)
        app_call = transaction.ApplicationCallTxn(
            sender=sponsor_address,
            sp=params,
            index=builder.payment_app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                method.get_selector(),
                recipient_arg,
                internal_id_arg
            ],
            accounts=[payer_address, merchant_address],  # Order matters!
            foreign_assets=[asset_id]
        )
        app_call.fee = 2000  # Fixed app call fee
        app_call.group = group_id_bytes
        
        # Step 5: Verify the rebuilt group matches user's group ID
        # Create Transaction objects from user signed data for verification
        user_txn1_obj = transaction.Transaction.undictify(txn1)
        user_txn2_obj = transaction.Transaction.undictify(txn2)
        
        # Calculate what the group ID should be
        from algosdk.transaction import calculate_group_id
        expected_gid = calculate_group_id([sponsor_payment, user_txn1_obj, user_txn2_obj, app_call])
        
        if expected_gid != group_id_bytes:
            logger.error(f"Group ID mismatch after rebuild!")
            logger.error(f"Expected: {base64.b64encode(expected_gid).decode()[:20]}...")
            logger.error(f"User has: {base64.b64encode(group_id_bytes).decode()[:20]}...")
            return False, "Failed to rebuild matching group - parameters don't match", None
        
        logger.info("Group ID matches! Signing sponsor transactions...")
        
        # Step 6: Sign sponsor transactions
        stx0 = signer.sign_transaction(sponsor_payment)
        stx3 = signer.sign_transaction(app_call)
        
        # Step 7: Prepare final byte array (keep user bytes unchanged)
        from algosdk import encoding as algo_encoding
        sponsor_b64_0 = algo_encoding.msgpack_encode(stx0)  # Returns base64 string
        sponsor_b64_3 = algo_encoding.msgpack_encode(stx3)  # Returns base64 string
        
        # Convert to raw bytes
        sponsor_bytes_0 = base64.b64decode(sponsor_b64_0)
        sponsor_bytes_3 = base64.b64decode(sponsor_b64_3)
        
        # Return in correct order: [sponsor_pay, user_axfer1, user_axfer2, sponsor_app]
        signed_txn_objects = [sponsor_bytes_0, user_txn1_bytes, user_txn2_bytes, sponsor_bytes_3]
        
        return True, None, signed_txn_objects
        
    except Exception as e:
        logger.error(f"Option B rebuild failed: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e), None
