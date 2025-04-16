from rest_framework import serializers
from .models import ZkLoginProof
import json

class ZkLoginProofSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZkLoginProof
        fields = '__all__'
        read_only_fields = ('created_at', 'verified_at', 'is_verified', 'firebase_uid', 'firebase_project_id')
        extra_kwargs = {
            'proof_data': {'write_only': True},
            'jwt': {'write_only': True},
            'randomness': {'write_only': True},
            'salt': {'write_only': True}
        }

    def validate_jwt(self, value):
        """Validate that the JWT is a Firebase ID token"""
        if not value:
            raise serializers.ValidationError("JWT token is required")
        # Additional validation will be done in the view
        return value

    def validate_proof_data(self, value):
        """Ensure proof_data is valid JSON"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError("proof_data must be valid JSON")
        return value 