from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from django.db import models, transaction
from django.utils import timezone

from .models import EligibilityDecision, EligibilityPolicy, EligibilityRule


def _country(value: Optional[str]) -> str:
    return (value or '').strip().upper()


@dataclass(frozen=True)
class EligibilityContext:
    nationality: str = ''
    residence_country: str = ''
    account_country: str = ''
    document_type: str = ''
    document_issuing_country: str = ''
    destination_country: str = ''

    def normalized(self):
        return EligibilityContext(
            nationality=_country(self.nationality),
            residence_country=_country(self.residence_country),
            account_country=_country(self.account_country),
            document_type=(self.document_type or '').strip().lower(),
            document_issuing_country=_country(self.document_issuing_country),
            destination_country=_country(self.destination_country),
        )


@dataclass(frozen=True)
class EvaluationResult:
    decision: str
    reason_code: str
    policy: EligibilityPolicy
    matched_rule: Optional[EligibilityRule]
    context: EligibilityContext

    @property
    def allowed(self):
        return self.decision == 'allow'


class EligibilityPolicyNotConfigured(RuntimeError):
    pass


class EligibilityDenied(PermissionError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'{result.decision}: {result.reason_code}')


_SELECTORS = (
    ('nationalities', 'nationality', _country),
    ('residence_countries', 'residence_country', _country),
    ('account_countries', 'account_country', _country),
    ('document_types', 'document_type', lambda value: (value or '').strip().lower()),
    ('document_issuing_countries', 'document_issuing_country', _country),
    ('destination_countries', 'destination_country', _country),
)


def rule_matches(rule: EligibilityRule, context: EligibilityContext) -> bool:
    for selector_name, context_name, normalizer in _SELECTORS:
        selector = getattr(rule, selector_name) or []
        if not isinstance(selector, list):
            return False
        if selector:
            allowed_values = {normalizer(value) for value in selector}
            if getattr(context, context_name) not in allowed_values:
                return False
    return True


def get_active_policy(provider: str, scope: str, at: Optional[datetime] = None):
    at = at or timezone.now()
    return (
        EligibilityPolicy.objects.filter(
            provider=provider,
            scope=scope,
            is_active=True,
            effective_from__lte=at,
        )
        .filter(models.Q(effective_until__isnull=True) | models.Q(effective_until__gt=at))
        .first()
    )


def evaluate_policy(policy: EligibilityPolicy, context: EligibilityContext) -> EvaluationResult:
    normalized = context.normalized()
    for rule in policy.rules.filter(is_active=True).order_by('priority', 'id'):
        if rule_matches(rule, normalized):
            return EvaluationResult(
                decision=rule.decision,
                reason_code=rule.reason_code,
                policy=policy,
                matched_rule=rule,
                context=normalized,
            )
    return EvaluationResult(
        decision=policy.default_decision,
        reason_code=policy.default_reason_code,
        policy=policy,
        matched_rule=None,
        context=normalized,
    )


def evaluate_active_policy(*, provider, scope, context, at=None):
    policy = get_active_policy(provider, scope, at=at)
    if policy is None:
        raise EligibilityPolicyNotConfigured(
            f'No active eligibility policy for provider={provider!r}, scope={scope!r}'
        )
    return evaluate_policy(policy, context)


def context_from_identity(
    identity_verification,
    *,
    account_country='',
    destination_country='',
):
    """Build policy input only from verified identity fields, never phone/IP guesses."""
    return EligibilityContext(
        nationality=identity_verification.verified_nationality,
        residence_country=identity_verification.verified_country,
        account_country=account_country,
        document_type=identity_verification.document_type,
        document_issuing_country=identity_verification.document_issuing_country,
        destination_country=destination_country,
    )


@transaction.atomic
def evaluate_and_record(*, confio_account, policy, context, money_flow=None):
    result = evaluate_policy(policy, context)
    decision = EligibilityDecision.objects.create(
        confio_account=confio_account,
        policy=policy,
        matched_rule=result.matched_rule,
        money_flow=money_flow,
        decision=result.decision,
        reason_code=result.reason_code,
        policy_version=policy.version,
        rule_snapshot=(
            {
                'priority': result.matched_rule.priority,
                'decision': result.matched_rule.decision,
                'reason_code': result.matched_rule.reason_code,
                'nationalities': result.matched_rule.nationalities,
                'residence_countries': result.matched_rule.residence_countries,
                'account_countries': result.matched_rule.account_countries,
                'document_types': result.matched_rule.document_types,
                'document_issuing_countries': result.matched_rule.document_issuing_countries,
                'destination_countries': result.matched_rule.destination_countries,
            }
            if result.matched_rule
            else {}
        ),
        context=asdict(result.context),
    )
    return result, decision


def enforce_and_record(*, confio_account, provider, scope, context, money_flow=None, at=None):
    policy = get_active_policy(provider, scope, at=at)
    if policy is None:
        raise EligibilityPolicyNotConfigured(
            f'No active eligibility policy for provider={provider!r}, scope={scope!r}'
        )
    result, decision = evaluate_and_record(
        confio_account=confio_account,
        policy=policy,
        context=context,
        money_flow=money_flow,
    )
    if not result.allowed:
        raise EligibilityDenied(result)
    return result, decision
