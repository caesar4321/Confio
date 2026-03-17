from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from p2p_exchange.models import P2PPaymentMethod
from users.models import Country


RAMP_USDC_ALGORAND_SYMBOL = "USDC-a"
RAMP_USDC_ALGORAND_NOTE = (
    "USDC-a todavía se enruta por USDC en Solana. "
    "Cámbialo a USDC en Algorand cuando Koywe soporte Algorand."
)
RAMP_NETWORK_SYMBOL = "USDC Solana"
RAMP_NETWORK_DISPLAY = "Solana"


COUNTRY_METHODS = {
    "AR": {
        "fiat_currency": "ARS",
        "rate": Decimal("1508.95"),
        "fee_percent": Decimal("1.815"),
        "network_fee_fiat": Decimal("13.60"),
        "on_ramp_min_amount": Decimal("100"),
        "on_ramp_max_amount": Decimal("8500000"),
        "off_ramp_min_amount": Decimal("0.10"),
        "off_ramp_max_amount": Decimal("5532.31"),
        "methods": [
            {
                "code": "WIREAR",
                "display_name": "Transferencia bancaria",
                "provider_type": "bank",
                "icon": "repeat",
                "description": "CBU/CVU o cuenta bancaria a nombre del usuario.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "KHIPU",
                "display_name": "Khipu",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Transferencia automatizada desde banco compatible.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": True,
                "supports_on_ramp": True,
                "supports_off_ramp": False,
            },
            {
                "code": "QRI-AR",
                "display_name": "QR interoperable",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Pago por QR interoperable en pesos argentinos.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": False,
            },
        ],
    },
    "BO": {
        "fiat_currency": "BOB",
        "rate": Decimal("9.785"),
        "fee_percent": Decimal("1.75"),
        "network_fee_fiat": Decimal("0.13"),
        "on_ramp_min_amount": Decimal("1"),
        "on_ramp_max_amount": Decimal("56000"),
        "off_ramp_min_amount": Decimal("0.10"),
        "off_ramp_max_amount": Decimal("5622.87"),
        "methods": [
            {
                "code": "QRI-BO",
                "display_name": "QR interoperable",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "SIP / QR interoperable boliviano.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
        ],
    },
    "BR": {
        "fiat_currency": "BRL",
        "rate": Decimal("5.202914"),
        "fee_percent": Decimal("1.50"),
        "network_fee_fiat": Decimal("0.05"),
        "on_ramp_min_amount": Decimal("1"),
        "on_ramp_max_amount": Decimal("45000"),
        "off_ramp_min_amount": Decimal("0.10"),
        "off_ramp_max_amount": Decimal("8519.25"),
        "methods": [
            {
                "code": "SULPAYMENTS",
                "display_name": "PIX transfer",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Transferencia PIX desde una cuenta PIX registrada.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "PIX_QR",
                "display_name": "PIX QR",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Pago con QR dinamico via PIX.",
                "requires_account_number": False,
                "requires_phone": True,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": False,
            },
        ],
    },
    "CL": {
        "fiat_currency": "CLP",
        "rate": Decimal("883.395"),
        "fee_percent": Decimal("1.785"),
        "network_fee_fiat": Decimal("9.00"),
        "on_ramp_min_amount": Decimal("1000"),
        "on_ramp_max_amount": Decimal("8500000"),
        "off_ramp_min_amount": Decimal("1"),
        "off_ramp_max_amount": Decimal("9450.20"),
        "methods": [
            {
                "code": "WIRECL",
                "display_name": "Transferencia bancaria",
                "provider_type": "bank",
                "icon": "repeat",
                "description": "Transferencia bancaria manual a nombre del usuario.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "KHIPU",
                "display_name": "Khipu",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Transferencia automatizada desde banco chileno.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": True,
                "supports_on_ramp": True,
                "supports_off_ramp": False,
            },
        ],
    },
    "CO": {
        "fiat_currency": "COP",
        "rate": Decimal("3816.228"),
        "fee_percent": Decimal("1.785"),
        "network_fee_fiat": Decimal("39.00"),
        "on_ramp_min_amount": Decimal("1000"),
        "on_ramp_max_amount": Decimal("41000000"),
        "off_ramp_min_amount": Decimal("1"),
        "off_ramp_max_amount": Decimal("10550.96"),
        "methods": [
            {
                "code": "PSE",
                "display_name": "PSE",
                "provider_type": "fintech",
                "icon": "repeat",
                "description": "Pago en línea con enlace PSE.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": True,
                "supports_on_ramp": True,
                "supports_off_ramp": False,
            },
            {
                "code": "NEQUI",
                "display_name": "Nequi",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Billetera movil Nequi.",
                "requires_account_number": False,
                "requires_phone": True,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "BANCOLOMBIA",
                "display_name": "Bancolombia",
                "provider_type": "bank",
                "icon": "credit-card",
                "description": "Cuenta Bancolombia a nombre del usuario.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
        ],
    },
    "MX": {
        "fiat_currency": "MXN",
        "rate": Decimal("17.3234205"),
        "fee_percent": Decimal("1.74"),
        "network_fee_fiat": Decimal("0.17"),
        "on_ramp_min_amount": Decimal("100"),
        "on_ramp_max_amount": Decimal("500000"),
        "off_ramp_min_amount": Decimal("1"),
        "off_ramp_max_amount": Decimal("28370.30"),
        "methods": [
            {
                "code": "WIREMX",
                "display_name": "SPEI",
                "provider_type": "bank",
                "icon": "repeat",
                "description": "Transferencia SPEI o CLABE registrada.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "STP",
                "display_name": "STP",
                "provider_type": "bank",
                "icon": "credit-card",
                "description": "Cuenta STP vinculada para pagos y retiros.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
        ],
    },
    "PE": {
        "fiat_currency": "PEN",
        "rate": Decimal("3.40025"),
        "fee_percent": Decimal("1.77"),
        "network_fee_fiat": Decimal("0.03"),
        "on_ramp_min_amount": Decimal("1"),
        "on_ramp_max_amount": Decimal("30000"),
        "off_ramp_min_amount": Decimal("0.10"),
        "off_ramp_max_amount": Decimal("8666.70"),
        "methods": [
            {
                "code": "WIREPE",
                "display_name": "Transferencia bancaria",
                "provider_type": "bank",
                "icon": "repeat",
                "description": "Cuenta bancaria peruana en soles.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "QRI-PE",
                "display_name": "QR interoperable",
                "provider_type": "fintech",
                "icon": "smartphone",
                "description": "Ligo QR interbancario.",
                "requires_account_number": False,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
            {
                "code": "RECAUDO-PE",
                "display_name": "Recaudo BCP",
                "provider_type": "bank",
                "icon": "credit-card",
                "description": "Cuenta BCP Peru en soles.",
                "requires_account_number": True,
                "requires_phone": False,
                "requires_email": False,
                "supports_on_ramp": True,
                "supports_off_ramp": True,
            },
        ],
    },
    "US": {
        "fiat_currency": "USD",
        "rate": Decimal("1.0025"),
        "fee_percent": Decimal("1.77"),
        "network_fee_fiat": Decimal("0.01"),
        "on_ramp_min_amount": Decimal("1"),
        "on_ramp_max_amount": Decimal("8000"),
        "off_ramp_min_amount": Decimal("1"),
        "off_ramp_max_amount": Decimal("7838.79"),
        "methods": [],
    },
}


def get_country_ramp_config(country_code: str | None):
    if not country_code:
        return None
    return COUNTRY_METHODS.get(country_code.upper())


def get_supported_country_codes(*, include_empty_methods: bool = False) -> list[str]:
    codes = []
    for country_code, config in COUNTRY_METHODS.items():
        if include_empty_methods or config["methods"]:
            codes.append(country_code)
    return sorted(codes)


def sync_country_payment_methods(country_code: str) -> list[P2PPaymentMethod]:
    config = get_country_ramp_config(country_code)
    if not config:
        return []

    country = Country.objects.filter(code=country_code.upper()).first()
    methods = []

    for index, method in enumerate(config["methods"], start=1):
        defaults = {
            "display_name": method["display_name"],
            "provider_type": method["provider_type"],
            "is_active": True,
            "icon": method["icon"],
            "country": country,
            "description": method["description"],
            "requires_phone": method["requires_phone"],
            "requires_email": method["requires_email"],
            "requires_account_number": method["requires_account_number"],
            "display_order": index * 10,
        }
        payment_method, _ = P2PPaymentMethod.objects.update_or_create(
            name=method["code"].lower().replace("-", "_"),
            country_code=country_code.upper(),
            defaults=defaults,
        )
        methods.append(payment_method)

    P2PPaymentMethod.objects.filter(
        country_code=country_code.upper(),
        name__startswith="wire",
    ).exclude(
        name__in=[m["code"].lower().replace("-", "_") for m in config["methods"]]
    ).update(is_active=False)

    return methods


def sync_all_country_payment_methods() -> list[P2PPaymentMethod]:
    synced_methods: list[P2PPaymentMethod] = []
    for country_code in get_supported_country_codes(include_empty_methods=False):
        synced_methods.extend(sync_country_payment_methods(country_code))
    return synced_methods


def deactivate_unsupported_payment_methods() -> int:
    supported_codes = set(get_supported_country_codes(include_empty_methods=False))
    supported_pairs = {
        (country_code, method["code"].lower().replace("-", "_"))
        for country_code, config in COUNTRY_METHODS.items()
        for method in config["methods"]
    }

    updated_count = 0
    for payment_method in P2PPaymentMethod.objects.filter(is_active=True):
        pair = (payment_method.country_code or "", payment_method.name)
        if pair in supported_pairs:
            continue
        if payment_method.country_code not in supported_codes:
            payment_method.is_active = False
            payment_method.save(update_fields=["is_active", "updated_at"])
            updated_count += 1
            continue
        if pair not in supported_pairs:
            payment_method.is_active = False
            payment_method.save(update_fields=["is_active", "updated_at"])
            updated_count += 1

    return updated_count


def quote_ramp(*, direction: str, amount: Decimal, country_code: str, fiat_currency: str | None = None):
    config = get_country_ramp_config(country_code)
    if not config:
        raise ValueError("Unsupported country for mock ramp")

    fiat = fiat_currency or config["fiat_currency"]
    rate = config["rate"]
    fee_percent = config["fee_percent"] / Decimal("100")
    network_fee_fiat = config["network_fee_fiat"]

    if direction == "ON_RAMP":
        gross_usdc = amount / rate
        fee_usdc = gross_usdc * fee_percent
        network_fee_usdc = network_fee_fiat / rate
        amount_out = gross_usdc - fee_usdc - network_fee_usdc
        fee_amount = (amount * fee_percent).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        network_fee_amount = network_fee_fiat.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        total_change_display = f"{_fmt(amount)} {fiat} -> {_fmt(amount_out)} {RAMP_USDC_ALGORAND_SYMBOL}"
    else:
        gross_fiat = amount * rate
        fee_amount = (gross_fiat * fee_percent).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        network_fee_amount = network_fee_fiat.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        amount_out = gross_fiat - fee_amount - network_fee_amount
        total_change_display = f"{_fmt(amount)} {RAMP_USDC_ALGORAND_SYMBOL} -> {_fmt(amount_out)} {fiat}"

    return {
        "direction": direction,
        "fiat_currency": fiat,
        "country_code": country_code.upper(),
        "amount_in": amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        "amount_out": amount_out.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        "exchange_rate": rate.quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
        "fee_amount": fee_amount,
        "fee_currency": fiat,
        "network_fee_amount": network_fee_amount,
        "network_fee_currency": fiat,
        "rate_display": f"1 {RAMP_USDC_ALGORAND_SYMBOL} ~= {_fmt(rate)} {fiat}",
        "total_change_display": total_change_display,
        "token_symbol": RAMP_USDC_ALGORAND_SYMBOL,
        "network_symbol": RAMP_NETWORK_SYMBOL,
        "network_display": RAMP_NETWORK_DISPLAY,
        "asset_note": RAMP_USDC_ALGORAND_NOTE,
    }


def _fmt(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return format(normalized.normalize(), "f")
