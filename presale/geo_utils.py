def check_presale_eligibility(user):
    """
    Check if user is eligible for presale based on phone country.
    Blocks US ('US') and South Korea ('KR').
    Returns: (is_eligible: bool, error_message: str|None)
    """
    code = getattr(user, 'phone_country', None)
    
    if code == 'US':
        return False, "Lo sentimos, los residentes de Estados Unidos no pueden participar en la preventa."
    
    if code == 'KR':
        return False, "Lo sentimos, los ciudadanos/residentes de Corea del Sur no pueden participar en la preventa."
        
    return True, None
