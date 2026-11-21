// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {GmQuote, IGMTokenManager} from "ondo-stocks/ConfioStockRouter.sol";
import {IPancakeSmartRouter} from "crypto-swap/ConfioSwapRouter.sol";

/// Test doubles for what is OUTSIDE Confío: tokens, Ondo's oracle, Instant
/// Manager and GM, PancakeSwap and Chainlink. The Confío contracts in the
/// unit tests (CusdVault, CusdPlusVault, ConfioStockRouter,
/// ConfioSwapRouter) are the real ones.

contract MockToken is ERC20 {
    uint8 private immutable _dec;
    /// When set, every transfer reverts (a paused or frozen token).
    bool public broken;

    constructor(string memory n, uint8 dec) ERC20(n, n) {
        _dec = dec;
    }

    function decimals() public view override returns (uint8) {
        return _dec;
    }

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

    /// Test backdoor: a token that lets anyone burn a holder's balance.
    function seize(address from, uint256 amt) external {
        _burn(from, amt);
    }

    function setBroken(bool v) external {
        broken = v;
    }

    function _update(address from, address to, uint256 value) internal override {
        require(!broken || from == address(0), "token broken");
        super._update(from, to, value);
    }
}

contract MockOracle {
    uint256 public price = 1e18;

    function setPrice(uint256 p) external {
        price = p;
    }

    function getPrice() external view returns (uint256) {
        return price;
    }
}

/// Swaps USDT <-> USDY at the oracle price, no spread.
contract MockInstantManager {
    MockToken public usdt;
    MockToken public usdy;
    MockOracle public oracle;

    constructor(MockToken _usdt, MockToken _usdy, MockOracle _oracle) {
        usdt = _usdt;
        usdy = _usdy;
        oracle = _oracle;
    }

    function subscribe(address, uint256 depositAmount, uint256 minimumRwaReceived) external returns (uint256 out) {
        usdt.transferFrom(msg.sender, address(this), depositAmount);
        out = (depositAmount * 1e18) / oracle.price();
        require(out >= minimumRwaReceived, "im slippage");
        usdy.transfer(msg.sender, out);
    }

    function redeem(uint256 rwaAmount, address, uint256 minimumTokenReceived) external returns (uint256 out) {
        usdy.transferFrom(msg.sender, address(this), rwaAmount);
        out = (rwaAmount * oracle.price()) / 1e18;
        require(out >= minimumTokenReceived, "im slippage");
        usdt.transfer(msg.sender, out);
    }
}

/// GM as verified on-chain: mint credits the caller, redeem pays the caller,
/// both at the quote's own price. No signature check (Ondo's cannot be
/// produced in a test).
contract MockGM is IGMTokenManager {
    MockToken public usdt;
    address internal _usdon;
    bool public halted;

    constructor(MockToken _usdt, address usdon_) {
        usdt = _usdt;
        _usdon = usdon_;
    }

    function usdon() external view returns (address) {
        return _usdon;
    }

    function setHalted(bool v) external {
        halted = v;
    }

    function mintWithAttestation(GmQuote calldata quote, bytes memory, address depositToken, uint256 amount)
        external
        returns (uint256)
    {
        require(!halted, "gm: halted");
        require(IERC20(depositToken).transferFrom(msg.sender, address(this), amount), "deposit failed");
        MockToken(quote.asset).mint(msg.sender, quote.quantity);
        return quote.quantity;
    }

    function redeemWithAttestation(GmQuote calldata quote, bytes memory, address receiveToken, uint256 minOut)
        external
        returns (uint256 out)
    {
        require(!halted, "gm: halted");
        require(MockToken(quote.asset).transferFrom(msg.sender, address(this), quote.quantity), "stock failed");
        out = (quote.quantity * quote.price) / 1e18;
        require(out >= minOut, "gm: min receive");
        require(IERC20(receiveToken).transfer(msg.sender, out), "proceeds failed");
    }
}

/// PancakeSwap SmartRouter. Prices are USDT per WHOLE token (WAD); token
/// decimals are honoured. `haircutBps` models a manipulated route that
/// returns less than the market.
contract MockDex is IPancakeSmartRouter {
    MockToken public usdt;
    mapping(address => uint256) public priceUsd;
    uint256 public haircutBps;

    constructor(MockToken _usdt) {
        usdt = _usdt;
    }

    function setPrice(address token, uint256 p) external {
        priceUsd[token] = p;
    }

    function setHaircutBps(uint256 v) external {
        haircutBps = v;
    }

    function _settle(address tokenIn, address tokenOut, uint256 amountIn, uint256 minOut, address to)
        internal
        returns (uint256 out)
    {
        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "pull failed");
        if (tokenIn == address(usdt)) {
            out = (amountIn * 10 ** MockToken(tokenOut).decimals()) / priceUsd[tokenOut];
        } else {
            out = (amountIn * priceUsd[tokenIn]) / 10 ** MockToken(tokenIn).decimals();
        }
        out -= (out * haircutBps) / 10_000;
        require(out >= minOut, "Too little received");
        MockToken(tokenOut).mint(to, out);
    }

    function exactInput(ExactInputParams calldata p) external payable returns (uint256) {
        bytes memory path = p.path;
        address first;
        address last;
        assembly {
            first := shr(96, mload(add(path, 32)))
            last := shr(96, mload(add(add(path, 32), sub(mload(path), 20))))
        }
        return _settle(first, last, p.amountIn, p.amountOutMinimum, p.recipient);
    }

    function swapExactTokensForTokens(uint256 amountIn, uint256 amountOutMin, address[] calldata path, address to)
        external
        payable
        returns (uint256)
    {
        return _settle(path[0], path[path.length - 1], amountIn, amountOutMin, to);
    }
}

/// Chainlink AggregatorV3 subset.
contract MockFeed {
    int256 public answer;
    uint256 public updatedAt;
    uint8 public immutable decimals;

    constructor(int256 answer_, uint8 decimals_) {
        answer = answer_;
        decimals = decimals_;
        updatedAt = block.timestamp;
    }

    function set(int256 answer_, uint256 updatedAt_) external {
        answer = answer_;
        updatedAt = updatedAt_;
    }

    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80) {
        return (1, answer, updatedAt, updatedAt, 1);
    }
}

/// A venue that speaks ConfioSwapRouter.sell for CONFIO (5.5): pulls the
/// token and pays cUSD it was pre-funded with, at `priceUsd` per token.
contract MockConfioVenue {
    IERC20 public cusd;
    uint256 public priceUsd;

    constructor(IERC20 cusd_, uint256 priceUsd_) {
        cusd = cusd_;
        priceUsd = priceUsd_;
    }

    function setPrice(uint256 p) external {
        priceUsd = p;
    }

    function sell(uint8, address tokenIn, uint256 amountIn, bytes calldata, uint256, uint256, uint256)
        external
        returns (uint256 out)
    {
        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "pull failed");
        out = (amountIn * priceUsd) / 1e18;
        require(cusd.transfer(msg.sender, out), "pay failed");
    }
}

/// A sponsor that is a contract (like a router) trying to act as relayer.
contract SponsorContract {
    function call(address target, bytes calldata data) external returns (bool ok, bytes memory ret) {
        (ok, ret) = target.call(data);
    }
}

/// A hostile "swap router": answers `buy`, delivers a token, and makes one
/// of the caller's other balances fall through the token's own backdoor.
contract EvilSwapRouter {
    MockToken public victim;

    constructor(MockToken victim_) {
        victim = victim_;
    }

    function buy(uint8, uint256, uint256, bytes calldata, address tokenOut, uint256, uint256)
        external
        returns (uint256)
    {
        MockToken(tokenOut).mint(msg.sender, 1e10);
        victim.seize(msg.sender, 1);
        return 1e10;
    }
}
