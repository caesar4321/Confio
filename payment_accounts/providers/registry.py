from .cobre import CobreProvider
from .infinia import InfiniaProvider


def get_provider(provider):
    if provider == 'cobre':
        return CobreProvider()
    if provider == 'infinia':
        return InfiniaProvider()
    raise ValueError(f'Unsupported payment account provider: {provider}')
