from unittest.mock import Mock
from django.test import SimpleTestCase
from conversion.schema import ConvertUSDCToCUSD, ConvertCUSDToUSDC

class ConversionLimitTests(SimpleTestCase):
    def test_usdc_to_cusd_limit(self):
        root = None
        info = Mock()
        info.context.user.is_authenticated = True
        info.context.user.__bool__ = lambda x: True
        
        amount = "0.5"
        result = ConvertUSDCToCUSD.mutate(root, info, amount)
        
        self.assertFalse(result.success)
        self.assertIsNotNone(result.errors)
        print(f"USDC Error Result: {result.errors}")
        
        # Verify the new generic message
        target_msg = "El monto debe ser al menos 1"
        self.assertTrue(any(target_msg in str(err) for err in result.errors))
        
        # Verify it DOES NOT contain 'USDC' (to avoid frontend heuristic trigger)
        self.assertFalse(any("USDC" in str(err) for err in result.errors), "Error message should not contain 'USDC'")
        
        # Verify it is a clean string, not a stringified list
        # result.errors is a list of strings
        # Ideally it should be ["El monto..."]
        # So conversion to string shouldn't look like "['...']"
        # However, Python's list __str__ does look like that.
        # We check the first element.
        if result.errors:
            first_err = result.errors[0]
            self.assertFalse(first_err.startswith("['"), "Error should be a clean string, not stringified list")
            
        print("USDC -> cUSD limit test passed")

    def test_cusd_to_usdc_limit(self):
        root = None
        info = Mock()
        info.context.user.is_authenticated = True
        info.context.user.__bool__ = lambda x: True
        
        amount = "0.999999"
        result = ConvertCUSDToUSDC.mutate(root, info, amount)
        
        self.assertFalse(result.success)
        self.assertIsNotNone(result.errors)
        print(f"cUSD Error Result: {result.errors}")
        
        target_msg = "El monto debe ser al menos 1"
        self.assertTrue(any(target_msg in str(err) for err in result.errors))
        self.assertFalse(any("cUSD" in str(err) for err in result.errors), "Error message should not contain 'cUSD'")
        
        if result.errors:
            first_err = result.errors[0]
            self.assertFalse(first_err.startswith("['"), "Error should be a clean string, not stringified list")

        print("cUSD -> USDC limit test passed")

if __name__ == "__main__":
    test = ConversionLimitTests()
    test.test_usdc_to_cusd_limit()
    test.test_cusd_to_usdc_limit()
