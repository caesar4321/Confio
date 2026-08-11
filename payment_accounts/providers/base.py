from abc import ABC, abstractmethod


class ProviderCapabilityError(NotImplementedError):
    pass


class PaymentAccountProvider(ABC):
    """Boundary implemented by Cobre and Infinia without erasing their differences."""

    provider: str

    @abstractmethod
    def provision_profile(self, profile):
        raise NotImplementedError

    def sync_profile(self, profile):
        return profile.provider_data

    @abstractmethod
    def provision_account(self, financial_account):
        raise NotImplementedError

    @abstractmethod
    def sync_account(self, financial_account):
        raise NotImplementedError

    def create_funding_instruction(self, financial_account, *, kind, **kwargs):
        raise ProviderCapabilityError(
            f'{self.provider} does not support creating {kind} funding instructions'
        )

    def create_payin(self, operation):
        raise ProviderCapabilityError(f'{self.provider} does not support pay-ins')

    def provision_destination(self, destination):
        raise ProviderCapabilityError(f'{self.provider} does not provision payout destinations')

    @abstractmethod
    def create_payout(self, operation):
        raise NotImplementedError

    def create_transfer(self, operation):
        raise ProviderCapabilityError(f'{self.provider} does not support internal transfers')

    @abstractmethod
    def retrieve_operation_by_idempotency(self, operation):
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, raw_body, headers):
        raise NotImplementedError

    @abstractmethod
    def normalize_webhook(self, raw_body, headers):
        raise NotImplementedError
