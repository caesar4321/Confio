// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioToken — $CONFIO on BSC.
 *
 * The BEP-20 home of the token after the Algorand→BSC migration. Mirrors
 * the Algorand ASA (id 3351104258, unit CONFIO, 1B total) at the
 * EVM-native 18 decimals. The on-chain name is deliberately the ASCII
 * "Confio" (no accent): Etherscan-family explorers HTML-escape non-ASCII
 * token names ("Conf&#237;o") as anti-spoofing, and wallet/DEX rendering
 * varies — on-chain metadata stays plain ASCII, the accented "Confío"
 * lives in UI and branding. (Supersedes the accented first deployment at
 * 0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1, delisted + supply burned.)
 *
 * Deliberately has NO owner, NO minter and NO pause: the entire fixed
 * supply of 1,000,000,000 CONFIO is minted once, in the constructor, to
 * the treasury (the 3-of-5 Safe), and no privileged surface exists after
 * that. Distribution — presale-vault funding, Algorand-migration swaps,
 * rewards — is a treasury operation, not a token power. This is the same
 * trust posture as the ASA (fixed supply, manager burned) and the presale
 * vault (rules immutable): what the explorer shows is all there ever is.
 *
 * ERC20Permit (EIP-2612) is included so approvals can ride a signature
 * (useful beyond the 7702 batch rail); ERC20Burnable lets any holder —
 * including the treasury — destroy their own tokens, and nothing else.
 */

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Burnable} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

contract ConfioToken is ERC20, ERC20Burnable, ERC20Permit {
    uint256 public constant TOTAL_SUPPLY = 1_000_000_000e18;

    error ZeroAddress();

    constructor(address treasury)
        ERC20("Confio", "CONFIO")
        ERC20Permit("Confio")
    {
        if (treasury == address(0)) revert ZeroAddress();
        _mint(treasury, TOTAL_SUPPLY);
    }
}
