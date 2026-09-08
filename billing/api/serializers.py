from decimal import Decimal

from rest_framework import serializers

from billing.models import ObligationSubject


class RejectUnknownFieldsSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Expected a JSON object.')
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({
                key: ['Unknown field.'] for key in sorted(unknown)
            })
        return super().to_internal_value(data)


class SubjectWriteSerializer(RejectUnknownFieldsSerializer):
    external_id = serializers.CharField(max_length=255)
    subject_type = serializers.ChoiceField(
        choices=ObligationSubject.SUBJECT_TYPES, default='person')
    masked_reference = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default='')
    locale = serializers.CharField(max_length=16, required=False, default='es-PE')
    timezone = serializers.CharField(
        max_length=64, required=False, default='America/Lima')


class SubjectPatchSerializer(RejectUnknownFieldsSerializer):
    masked_reference = serializers.CharField(
        max_length=80, required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=('active', 'archived', 'blocked'), required=False)
    locale = serializers.CharField(max_length=16, required=False)
    timezone = serializers.CharField(max_length=64, required=False)


class CommercialAmountSerializer(RejectUnknownFieldsSerializer):
    value = serializers.DecimalField(
        max_digits=19, decimal_places=2, min_value=Decimal('0.01'),
        max_value=Decimal('92233720368547758.07'))
    currency = serializers.ChoiceField(choices=('PEN',))


class PeriodSerializer(RejectUnknownFieldsSerializer):
    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs['end'] < attrs['start']:
            raise serializers.ValidationError('Period end must not precede start.')
        return attrs


class ObligationCreateSerializer(RejectUnknownFieldsSerializer):
    external_id = serializers.CharField(max_length=255)
    subject = serializers.CharField(max_length=40)
    commercial_amount = CommercialAmountSerializer()
    period = PeriodSerializer()
    issued_at = serializers.DateTimeField(required=False)
    due_at = serializers.DateTimeField()
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default='')


class WebhookEndpointCreateSerializer(RejectUnknownFieldsSerializer):
    url = serializers.URLField(max_length=500)
    event_types = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, default=list,
        max_length=50)
    description = serializers.CharField(
        max_length=160, required=False, allow_blank=True, default='')


class WebhookEndpointPatchSerializer(RejectUnknownFieldsSerializer):
    status = serializers.ChoiceField(choices=('active', 'disabled'), required=False)
    description = serializers.CharField(max_length=160, required=False, allow_blank=True)
