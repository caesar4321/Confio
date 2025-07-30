from django.core.exceptions import ValidationError
from decimal import Decimal
import re

def validate_transaction_amount(amount) -> None:
    """Validate the transaction amount"""
    try:
        # Convert to Decimal for precise monetary calculations
        if isinstance(amount, str):
            amount_decimal = Decimal(amount)
        elif isinstance(amount, (int, float)):
            amount_decimal = Decimal(str(amount))
        elif isinstance(amount, Decimal):
            amount_decimal = amount
        else:
            raise ValueError(f"Invalid amount type: {type(amount)}")
        
        # Use decimal for comparison
        amount_float = float(amount_decimal)
        
        # Check if amount is positive
        if amount_float <= 0:
            raise ValidationError("Amount must be greater than 0")
            
        # Check if amount is within reasonable limits (max 1 million)
        if amount_float > 1_000_000:
            raise ValidationError("Amount exceeds maximum allowed (1,000,000)")
            
    except ValueError:
        raise ValidationError("Amount must be a valid number")

def validate_recipient(address: str) -> None:
    """Validate the recipient's Sui address"""
    # Sui addresses are 32 bytes (64 hex characters)
    if not re.match(r'^0x[0-9a-fA-F]{64}$', address):
        raise ValidationError("Invalid Sui address format") 