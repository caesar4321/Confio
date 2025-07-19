from django.core.exceptions import ValidationError
import re

def validate_transaction_amount(amount: str) -> None:
    """Validate the transaction amount"""
    try:
        # Convert to float to validate it's a valid number (handles decimals)
        amount_float = float(amount)
        
        # Check if amount is positive
        if amount_float <= 0:
            raise ValidationError("Amount must be greater than 0")
            
        # Check if amount is within reasonable limits (e.g., max 1 billion)
        if amount_float > 1_000_000_000_000_000:  # 1 billion with 6 decimals
            raise ValidationError("Amount exceeds maximum allowed")
            
    except ValueError:
        raise ValidationError("Amount must be a valid number")

def validate_recipient(address: str) -> None:
    """Validate the recipient's Sui address"""
    # Sui addresses are 32 bytes (64 hex characters)
    if not re.match(r'^0x[0-9a-fA-F]{64}$', address):
        raise ValidationError("Invalid Sui address format") 