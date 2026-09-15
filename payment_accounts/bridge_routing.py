"""New quotes use Relay; persisted NEXT transfers retain their own executor."""
from .relay import RelayClient


def quote_routes(source, destination, amount, sender, recipient, *, client=None):
    if client is not None:
        # Legacy adapter injection for existing NEXT flows and regression tests.
        return client.quote(source, destination, amount)
    return RelayClient().routes(source, destination, amount, sender, recipient)
