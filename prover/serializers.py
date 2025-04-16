from rest_framework import serializers
from .models import ZkLoginProof

class ZkLoginProofSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZkLoginProof
        fields = '__all__'
        read_only_fields = ('created_at', 'verified_at', 'is_verified')
        extra_kwargs = {
            'proof_data': {'write_only': True},
            'jwt': {'write_only': True},
            'randomness': {'write_only': True},
            'salt': {'write_only': True}
        } 