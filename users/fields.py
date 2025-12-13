from django.db import models
from .encryption import encrypt_data, decrypt_data

class EncryptedCharField(models.CharField):
    """
    A CharField that transparently encrypts data when saving to DB 
    and decrypts when loading from DB.
    """
    description = "Encrypted character string"

    def get_db_prep_value(self, value, connection, prepared=False):
        """Encrypt data before saving to DB"""
        if value is None:
            return None
        # If it's already encrypted (starts with gAAAA - Fernet prefix standard? No, Fernet result is base64)
        # We rely on application logic to not double-encrypt, or we just encrypt whatever is passed.
        # Ideally, we encrypt.
        # Note: This is called when saving.
        return encrypt_data(str(value))

    def from_db_value(self, value, expression, connection):
        """Decrypt data when loading from DB"""
        if value is None:
            return None
        return decrypt_data(value)

    def to_python(self, value):
        """
        Convert the input value into the expected Python data type, raising
        django.core.exceptions.ValidationError if the data can't be converted.
        This method is called when the field value is assigned to the model attribute.
        """
        if value is None:
            return value
        # This is tricky in Django. to_python is called during deserialization 
        # AND when assigning from forms.
        # But generally, we want the python object to hold the PLAINTEXT.
        # The DB holds the CIPHERTEXT.
        # from_db_value handles DB -> Python.
        return value
