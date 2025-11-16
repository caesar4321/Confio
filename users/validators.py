import re
from django.core.exceptions import ValidationError

def validate_username(username):
    """
    Validate username format and length.
    
    Args:
        username (str): The username to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not username:
        return False, "Username is required"
    
    username = username.strip()
    
    # Check minimum length
    if len(username) < 3:
        return False, "El nombre de usuario debe tener al menos 3 caracteres"
    
    # Check maximum length
    if len(username) > 20:
        return False, "El nombre de usuario no puede tener más de 20 caracteres"
    
    # Check format (only letters, numbers, and underscores)
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Solo se permiten letras, números y guiones bajos (_)"
    
    return True, None

def validate_username_django(username):
    """
    Django validator function for username field.
    
    Args:
        username (str): The username to validate
        
    Raises:
        ValidationError: If username is invalid
    """
    is_valid, error_message = validate_username(username)
    if not is_valid:
        raise ValidationError(error_message) 
