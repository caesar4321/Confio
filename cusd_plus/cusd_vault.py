"""Read-only helpers for the BSC cUSD conversion-fee perimeter.

Binding monetary quotes come from the deployed contract. Python exposes the
decoded values but never reimplements fee rounding for production decisions.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from eth_utils import keccak


WAD = 10 ** 18


def _sel(signature: str) -> str:
    return '0x' + keccak(text=signature)[:4].hex()


SEL_FEE_BPS = _sel('feeBps()')
SEL_FEE_FOR = _sel('feeFor(uint256)')
SEL_PREVIEW_MINT = _sel('previewMint(uint256)')
SEL_PREVIEW_REDEEM = _sel('previewRedeem(uint256)')
SEL_PAUSED = _sel('paused()')
SEL_TOTAL_SUPPLY = _sel('totalSupply()')
SEL_BACKING_USDT = _sel('backingUsdt()')
SEL_ACCRUED_ENTRY_FEES = _sel('accruedEntryFees()')
SEL_ACCRUED_EXIT_FEES = _sel('accruedExitFees()')


@dataclass(frozen=True)
class ConversionPreview:
    gross_wei: int
    fee_wei: int
    net_wei: int
    fee_bps: int

    @property
    def gross(self) -> Decimal:
        return Decimal(self.gross_wei) / WAD

    @property
    def fee(self) -> Decimal:
        return Decimal(self.fee_wei) / WAD

    @property
    def net(self) -> Decimal:
        return Decimal(self.net_wei) / WAD


def vault_address() -> str:
    return (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()


def _rpc(method: str, params: list):
    from .tasks import _rpc as tasks_rpc
    return tasks_rpc(method, params)


def _call_words(data: str, count: int) -> tuple[int, ...]:
    address = vault_address()
    if not address:
        raise RuntimeError('cusd_vault_not_configured')
    raw = _rpc('eth_call', [{'to': address, 'data': data}, 'latest'])
    body = (raw or '').removeprefix('0x')
    if len(body) != 64 * count:
        raise RuntimeError('cusd_vault_bad_response')
    return tuple(int(body[i * 64:(i + 1) * 64], 16) for i in range(count))


def _uint_call(selector: str, value: int | None = None, words: int = 1) -> tuple[int, ...]:
    data = selector
    if value is not None:
        if value < 0 or value >= 2 ** 256:
            raise ValueError('amount_out_of_range')
        data += f'{value:064x}'
    return _call_words(data, words)


def current_fee_bps() -> int:
    return _uint_call(SEL_FEE_BPS)[0]


def total_supply_wei() -> int:
    return _uint_call(SEL_TOTAL_SUPPLY)[0]


def backing_usdt_wei() -> int:
    """USDT reserved for holders, excluding accrued Confío fees."""
    return _uint_call(SEL_BACKING_USDT)[0]


def accrued_entry_fees_wei() -> int:
    return _uint_call(SEL_ACCRUED_ENTRY_FEES)[0]


def accrued_exit_fees_wei() -> int:
    return _uint_call(SEL_ACCRUED_EXIT_FEES)[0]


def is_paused() -> bool:
    """Fail closed when the cUSD perimeter cannot accept normal flows."""
    return bool(_uint_call(SEL_PAUSED)[0])


def require_operational() -> None:
    address = vault_address()
    if not address:
        raise RuntimeError('cusd_vault_not_configured')
    code = _rpc('eth_getCode', [address, 'latest'])
    if not code or code == '0x':
        raise RuntimeError('cusd_vault_not_deployed')
    if is_paused():
        raise RuntimeError('cusd_vault_paused')


def fee_for_wei(gross_wei: int) -> int:
    return _uint_call(SEL_FEE_FOR, int(gross_wei))[0]


def _preview(selector: str, gross_wei: int) -> ConversionPreview:
    gross = int(gross_wei)
    fee, net = _uint_call(selector, gross, words=2)
    if gross < 0 or fee < 0 or net < 0 or fee + net != gross:
        raise RuntimeError('cusd_vault_invalid_preview')
    bps = current_fee_bps()
    if bps < 0 or bps > 90:
        raise RuntimeError('cusd_vault_invalid_fee_bps')
    return ConversionPreview(gross_wei=gross, fee_wei=fee, net_wei=net, fee_bps=bps)


def preview_mint_wei(gross_wei: int) -> ConversionPreview:
    return _preview(SEL_PREVIEW_MINT, gross_wei)


def preview_redeem_wei(gross_wei: int) -> ConversionPreview:
    return _preview(SEL_PREVIEW_REDEEM, gross_wei)
