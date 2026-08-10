"""Run a minimum-size Ondo Stocks buy/sell round trip from the BSC KMS sponsor.

The command is deliberately resumable. If an earlier attempt bought stock but
did not sell it, the next run skips funding and buying and exits the exact live
stock balance. Dry-run is the default; production writes require both flags.
"""
from decimal import Decimal, ROUND_DOWN
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from eth_abi import decode as abi_decode, encode as abi_encode
from eth_utils import keccak, to_checksum_address

from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
from blockchain.management.commands.deploy_stock_router import (
    CUSD_PLUS,
    GM_TOKEN_MANAGER,
    SAFE,
    USDT,
    _rpc,
)
from cusd_plus import gm_api
from cusd_plus.schema import _normalize_gm_quote, _validated_gm_trade_request


CHAIN_ID = 56
WAD = 10**18
BPS = 10_000
FEE_BPS = 30
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
DEFAULT_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
DEFAULT_SYMBOL = "TSLAon"
DEFAULT_GROSS = Decimal("1.10")
DEFAULT_SAVINGS_FUND = Decimal("1.30")
SWAP_BNB_WEI = 3_000_000_000_000_000
MAX_UINT256 = 2**256 - 1


def _selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def _calldata(signature: str, types: list[str], values: list) -> str:
    return "0x" + (_selector(signature) + abi_encode(types, values)).hex()


def _call(rpc_url: str, to: str, signature: str, types=None, values=None, outputs=None):
    data = _calldata(signature, types or [], values or [])
    raw = _rpc(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"])
    if not outputs:
        return raw
    decoded = abi_decode(outputs, bytes.fromhex(raw.removeprefix("0x")))
    return decoded[0] if len(decoded) == 1 else decoded


def _wei_text(value: int) -> str:
    whole, fraction = divmod(value, WAD)
    tail = str(fraction).rjust(18, "0").rstrip("0")
    return f"{whole}.{tail}" if tail else str(whole)


def _quote_tuple(quote: dict):
    return (
        int(quote["chain_id"]),
        int(quote["attestation_id"]),
        bytes.fromhex(quote["user_id"].removeprefix("0x")),
        to_checksum_address(quote["asset_address"]),
        int(quote["price"]),
        int(quote["token_amount"]),
        int(quote["expiration"]),
        int(quote["side"]),
        bytes.fromhex(quote["additional_data_hex"].removeprefix("0x")),
    )


class Command(BaseCommand):
    help = "Dry-run or execute a KMS-owned minimum Ondo Stocks round trip"

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--yes-mainnet", action="store_true")
        parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
        parser.add_argument("--gross-usd", default=str(DEFAULT_GROSS))

    def handle(self, *args, **options):
        execute = bool(options["execute"])
        if execute and not options["yes_mainnet"]:
            raise CommandError("--execute requires --yes-mainnet")
        if int(settings.BSC_CHAIN_ID) != CHAIN_ID:
            raise CommandError("BSC_CHAIN_ID must be 56")
        if getattr(settings, "CUSD_PLUS_STOCK_TRADING_ENABLED", False):
            raise CommandError("Refusing canary after public stock trading is enabled")

        rpc_url = settings.BSC_RPC_URL
        if int(_rpc(rpc_url, "eth_chainId", []), 16) != CHAIN_ID:
            raise CommandError("RPC is not BSC mainnet")
        signer = get_bsc_sponsor_signer_from_settings()
        account = signer.address
        router = to_checksum_address(settings.CUSD_PLUS_STOCK_ROUTER_ADDRESS)
        if not router:
            raise CommandError("CUSD_PLUS_STOCK_ROUTER_ADDRESS is not configured")
        pancake = to_checksum_address(
            getattr(settings, "CUSD_PLUS_PANCAKE_ROUTER", "") or DEFAULT_ROUTER
        )
        symbol = str(options["symbol"]).strip()
        gross = Decimal(str(options["gross_usd"]))
        if gross < Decimal("1.05") or gross > Decimal("5"):
            raise CommandError("--gross-usd must be between 1.05 and 5.00")

        registry = _call(
            rpc_url, GM_TOKEN_MANAGER, "ondoIDRegistry()", outputs=["address"]
        )
        identifier = _call(
            rpc_url, GM_TOKEN_MANAGER, "gmIdentifier()", outputs=["address"]
        )
        purchaser_id = _call(
            rpc_url,
            registry,
            "getRegisteredID(address,address)",
            ["address", "address"],
            [identifier, router],
            ["bytes32"],
        )
        if purchaser_id == bytes(32):
            raise CommandError("Router is not registered in Ondo GM")
        if not _call(
            rpc_url,
            CUSD_PLUS,
            "isSponsor(address)",
            ["address"],
            [router],
            ["bool"],
        ):
            raise CommandError("Router is not a cUSD+ sponsor")
        if not _call(
            rpc_url,
            CUSD_PLUS,
            "isSponsor(address)",
            ["address"],
            [account],
            ["bool"],
        ):
            raise CommandError("KMS canary account is not a cUSD+ sponsor")
        if _call(rpc_url, router, "owner()", outputs=["address"]).lower() != SAFE.lower():
            raise CommandError("Router owner is not the Confio Safe")
        if _call(rpc_url, router, "stockFeeBps()", outputs=["uint256"]) != FEE_BPS:
            raise CommandError("Router fee is not 30 bps")

        token_file = settings.BASE_DIR / "cusd_plus" / "gm_tokens.json"
        token_row = json.loads(token_file.read_text()).get(symbol)
        if not token_row:
            raise CommandError(f"Unknown snapshot symbol: {symbol}")
        stock = to_checksum_address(token_row["address"])

        def balance(token: str) -> int:
            return _call(
                rpc_url,
                token,
                "balanceOf(address)",
                ["address"],
                [account],
                ["uint256"],
            )

        def allowance(token: str, spender: str) -> int:
            return _call(
                rpc_url,
                token,
                "allowance(address,address)",
                ["address", "address"],
                [account, spender],
                ["uint256"],
            )

        def send(to: str, data: str, *, label: str, value: int = 0) -> str:
            nonce = int(
                _rpc(rpc_url, "eth_getTransactionCount", [account, "pending"]), 16
            )
            gas_price = max(
                int(_rpc(rpc_url, "eth_gasPrice", []), 16),
                int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
            )
            gas_price = gas_price * 12 // 10
            call = {"from": account, "to": to, "data": data, "value": hex(value)}
            gas = int(_rpc(rpc_url, "eth_estimateGas", [call]), 16)
            tx = {
                "chainId": CHAIN_ID,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": gas * 13 // 10,
                "to": to,
                "value": value,
                "data": data,
            }
            raw, local_hash = signer.sign_transaction(tx)
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            if sent.lower() != local_hash.lower():
                raise CommandError(f"{label} transaction hash mismatch")
            receipt = None
            for _ in range(60):
                receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if receipt:
                    break
                time.sleep(2)
            if not receipt:
                raise CommandError(f"Timeout waiting for {label}: {sent}")
            if receipt["status"] != "0x1":
                raise CommandError(f"{label} reverted: {sent}")
            self.stdout.write(f"{label}: {sent}")
            return sent

        self.stdout.write(f"Account: {account}")
        self.stdout.write(f"Router:  {router}")
        self.stdout.write(f"Ondo ID: 0x{purchaser_id.hex()}")
        self.stdout.write(f"Symbol:  {symbol} ({stock})")
        self.stdout.write(f"Gross:   ${gross}")
        self.stdout.write(
            f"Balances: {_wei_text(balance(USDT))} USDT, "
            f"{_wei_text(balance(CUSD_PLUS))} cUSD+, {_wei_text(balance(stock))} {symbol}"
        )

        existing_stock = balance(stock)
        if not execute:
            if existing_stock == 0:
                spend = int(
                    (gross * Decimal(WAD) * Decimal(BPS - FEE_BPS) / Decimal(BPS))
                    .quantize(Decimal("1"), rounding=ROUND_DOWN)
                )
                request = _validated_gm_trade_request(
                    symbol, "buy", _wei_text(spend), "short"
                )
                quote = _normalize_gm_quote(
                    gm_api.soft_attestation(**request), request, binding=False
                )
                self.stdout.write(
                    f"Soft buy quote: {_wei_text(int(quote['notional_wei']))} USDT -> "
                    f"{_wei_text(int(quote['token_amount']))} {symbol}"
                )
            else:
                self.stdout.write("Existing stock will be sold; no new buy is planned.")
            self.stdout.write(self.style.WARNING("DRY RUN — no transaction or binding quote sent"))
            return

        # Resume safety: a nonzero stock balance always goes directly to the
        # sell leg. This makes a buy-success/sell-failure recoverable.
        if existing_stock == 0:
            fund_wei = int(DEFAULT_SAVINGS_FUND * Decimal(WAD))
            usdt_balance = balance(USDT)
            if usdt_balance < fund_wei:
                bnb_balance = int(_rpc(rpc_url, "eth_getBalance", [account, "latest"]), 16)
                if bnb_balance < SWAP_BNB_WEI + 2_000_000_000_000_000:
                    raise CommandError("Insufficient BNB for canary funding plus gas reserve")
                amounts = _call(
                    rpc_url,
                    pancake,
                    "getAmountsOut(uint256,address[])",
                    ["uint256", "address[]"],
                    [SWAP_BNB_WEI, [WBNB, USDT]],
                    ["uint256[]"],
                )
                min_out = int(amounts[-1]) * 99 // 100
                swap_data = _calldata(
                    "swapExactETHForTokens(uint256,address[],address,uint256)",
                    ["uint256", "address[]", "address", "uint256"],
                    [min_out, [WBNB, USDT], account, int(time.time()) + 600],
                )
                send(pancake, swap_data, label="BNB -> USDT funding", value=SWAP_BNB_WEI)
                usdt_balance = balance(USDT)
            if usdt_balance < fund_wei:
                raise CommandError("Canary funding produced insufficient USDT")

            if balance(CUSD_PLUS) < int(gross * Decimal(WAD)):
                if allowance(USDT, CUSD_PLUS) < fund_wei:
                    send(
                        USDT,
                        _calldata(
                            "approve(address,uint256)",
                            ["address", "uint256"],
                            [CUSD_PLUS, MAX_UINT256],
                        ),
                        label="Approve USDT -> cUSD+",
                    )
                oracle_price = _call(
                    rpc_url, CUSD_PLUS, "lastOraclePrice()", outputs=["uint256"]
                )
                min_usdy = (fund_wei * WAD // oracle_price) * 99 // 100
                send(
                    CUSD_PLUS,
                    _calldata(
                        "subscribeAndMint(uint256,uint256,address)",
                        ["uint256", "uint256", "address"],
                        [fund_wei, min_usdy, account],
                    ),
                    label="Fund cUSD+ canary position",
                )

            spend = int(
                (gross * Decimal(WAD) * Decimal(BPS - FEE_BPS) / Decimal(BPS))
                .quantize(Decimal("1"), rounding=ROUND_DOWN)
            )
            request = _validated_gm_trade_request(
                symbol, "buy", _wei_text(spend), "short"
            )
            buy_quote = _normalize_gm_quote(
                gm_api.binding_attestation(**request), request, binding=True
            )
            spend = int(buy_quote["notional_wei"])
            fee = (spend * FEE_BPS + (BPS - FEE_BPS) - 1) // (BPS - FEE_BPS)
            required = spend + fee
            p_plus = _call(rpc_url, CUSD_PLUS, "pPlus()", outputs=["uint256"])
            shares = (required * WAD + p_plus - 1) // p_plus + 2
            if shares > balance(CUSD_PLUS):
                raise CommandError("Canary cUSD+ balance cannot cover binding quote")
            if allowance(CUSD_PLUS, router) < shares:
                send(
                    CUSD_PLUS,
                    _calldata(
                        "approve(address,uint256)",
                        ["address", "uint256"],
                        [router, MAX_UINT256],
                    ),
                    label="Approve cUSD+ -> stock router",
                )
            quote_type = "(uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32)"
            buy_data = _calldata(
                "buyWithSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256,uint256)",
                [quote_type, "bytes", "uint256", "uint256", "uint256", "uint256"],
                [
                    _quote_tuple(buy_quote),
                    bytes.fromhex(buy_quote["signature_hex"].removeprefix("0x")),
                    shares,
                    spend,
                    required,
                    FEE_BPS,
                ],
            )
            send(router, buy_data, label="Ondo Stocks canary buy")
            existing_stock = balance(stock)
            if existing_stock < int(buy_quote["token_amount"]):
                raise CommandError("Canary buy did not deliver the signed stock quantity")

        # Exact-balance sell. Use a soft quote to seed the current price, then
        # bind and re-bind until Ondo's signed quantity equals the live balance.
        held = balance(stock)
        if held <= 0:
            raise CommandError("No stock balance available for canary sell")
        seed_request = _validated_gm_trade_request(symbol, "sell", str(gross), "short")
        seed = _normalize_gm_quote(
            gm_api.soft_attestation(**seed_request), seed_request, binding=False
        )
        price = int(seed["price"])
        sell_quote = None
        for _ in range(3):
            notional = (held * price + WAD - 1) // WAD
            request = _validated_gm_trade_request(
                symbol, "sell", _wei_text(notional), "short"
            )
            sell_quote = _normalize_gm_quote(
                gm_api.binding_attestation(**request), request, binding=True
            )
            if int(sell_quote["token_amount"]) == held:
                break
            price = int(sell_quote["price"])
        if sell_quote is None or int(sell_quote["token_amount"]) != held:
            raise CommandError("Could not obtain an exact-balance sell attestation")
        if allowance(stock, router) < held:
            send(
                stock,
                _calldata(
                    "approve(address,uint256)",
                    ["address", "uint256"],
                    [router, MAX_UINT256],
                ),
                label=f"Approve {symbol} -> stock router",
            )
        quote_cost = held * int(sell_quote["price"]) // WAD
        min_usdt = quote_cost * 99 // 100
        net = quote_cost - quote_cost * FEE_BPS // BPS
        p_plus = _call(rpc_url, CUSD_PLUS, "pPlus()", outputs=["uint256"])
        oracle_price = _call(
            rpc_url, CUSD_PLUS, "lastOraclePrice()", outputs=["uint256"]
        )
        expected_shares = (net * WAD // oracle_price) * oracle_price // p_plus
        min_shares = expected_shares * 99 // 100
        if min_usdt <= 0 or min_shares <= 0:
            raise CommandError("Canary sell floors are zero")
        sell_data = _calldata(
            "sellToSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256)",
            [
                "(uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32)",
                "bytes",
                "uint256",
                "uint256",
                "uint256",
            ],
            [
                _quote_tuple(sell_quote),
                bytes.fromhex(sell_quote["signature_hex"].removeprefix("0x")),
                min_usdt,
                min_shares,
                FEE_BPS,
            ],
        )
        send(router, sell_data, label="Ondo Stocks canary sell")
        if balance(stock) != 0:
            raise CommandError("Canary sell left a nonzero stock balance")

        self.stdout.write(self.style.SUCCESS("CANARY PASSED: exact stock round trip completed"))
        self.stdout.write(
            f"Final balances: {_wei_text(balance(USDT))} USDT, "
            f"{_wei_text(balance(CUSD_PLUS))} cUSD+, 0 {symbol}"
        )
