// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioInviteEscrow — BSC mirror of the Algorand invite & send escrow
 * (contracts/invite_send/invite_send.py).
 *
 * An inviter locks cUSD+, cUSD or CONFIO for someone who is NOT yet a Confío
 * user (identified off-chain by phone/email). The invitee's on-chain
 * address is unknown at create time, so the CLAIM is authorized by the
 * backend SPONSOR, which ties the phone/invite to the joining user's
 * verified BSC address and releases the escrow to them. If nobody claims
 * within the reclaim window, the inviter takes it back.
 *
 * Model (Algorand parity):
 *  - createInvitation(inviteId, token, amount): inviter's 7702 batch is
 *    [token.approve(this, amount), createInvitation(...)]; the escrow pulls
 *    the tokens. `inviteId` is a backend-generated opaque key.
 *  - claimInvitation(inviteId, inviter, recipient, eligibility, minOut):
 *    SPONSOR-only, before expiry —
 *    releases to the recipient the backend verified. Never gated further:
 *    the sponsor IS the authorization (as on Algorand: sender ∈ {recipient,
 *    admin, sponsor}, and only the backend knows the recipient).
 *  - reclaimInvitation(inviteId): the INVITER only, after expiry.
 *
 * Dollar claims are eligibility-aware. The sponsor passes the recipient's
 * current Ondo eligibility, and the escrow atomically converts cUSD+ -> cUSD
 * or cUSD -> cUSD+ through the fee-free internal wrapper boundary when the
 * locked representation does not match. No raw USDT is ever held here.
 *
 * Only cUSD+, cUSD and CONFIO are escrowable. Owner = the 3-of-5 Safe (rotate the
 * sponsor, pause NEW invites/claims — reclaim is never pausable, an exit).
 * Non-upgradeable; the escrow holds only in-flight invites.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

interface IInviteCusdPlus is IERC20 {
    function unwrapToCusd(uint256 shares, uint256 minCusdOut, address to) external returns (uint256 cusdOut);

    function wrapCusd(uint256 cusdIn, uint256 minUsdyOut, address recipient) external returns (uint256 sharesOut);
}

contract ConfioInviteEscrow is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    uint64 public constant RECLAIM_PERIOD = 7 days;

    IInviteCusdPlus public immutable CUSD_PLUS;
    IERC20 public immutable CUSD;
    IERC20 public immutable CONFIO;

    /// Backend key that authorizes claims to a verified recipient.
    address public sponsor;

    struct Invitation {
        address inviter;
        address token; // CUSD_PLUS, CUSD or CONFIO
        uint128 amount;
        uint64 expiresAt;
        bool settled; // claimed or reclaimed
    }

    /// Keyed by (inviter, inviteId), NOT inviteId alone (audit 2026-07-31
    /// [P3]): the inviteId is derived from the recipient's phone and is
    /// therefore public-derivable, so a global key would let anyone squat a
    /// target's invite id with a 1-wei create and permanently block real
    /// invites to that person. Namespacing by the actual creator means a
    /// squatter's entry lands under THEIR key, not the real inviter's — and
    /// it lets several people invite the same phone independently.
    mapping(bytes32 => Invitation) public invitations;

    function invitationKey(address inviter, bytes32 inviteId) public pure returns (bytes32) {
        return keccak256(abi.encode(inviter, inviteId));
    }

    event SponsorSet(address indexed sponsor);
    event InvitationCreated(
        bytes32 indexed inviteId, address indexed inviter, address token, uint256 amount, uint64 expiresAt
    );
    event InvitationClaimed(
        bytes32 indexed inviteId, address indexed recipient, address indexed tokenOut, uint256 amountOut
    );
    event InvitationReclaimed(bytes32 indexed inviteId, address indexed inviter, uint256 amount);

    constructor(address cusdPlus, address cusd, address confio, address sponsor_, address owner_) Ownable(owner_) {
        require(
            cusdPlus != address(0) && cusd != address(0) && confio != address(0) && sponsor_ != address(0),
            "zero address"
        );
        require(cusdPlus.code.length > 0 && cusd.code.length > 0 && confio.code.length > 0, "not contract");
        CUSD_PLUS = IInviteCusdPlus(cusdPlus);
        CUSD = IERC20(cusd);
        CONFIO = IERC20(confio);
        sponsor = sponsor_;
        emit SponsorSet(sponsor_);
    }

    modifier onlySponsor() {
        require(msg.sender == sponsor, "not sponsor");
        _;
    }

    function _allowed(address token) private view returns (bool) {
        return token == address(CUSD_PLUS) || token == address(CUSD) || token == address(CONFIO);
    }

    // ═════════════════════════ Create ═══════════════════════════════════

    /// Lock `amount` of `token` under `inviteId`. Called by the inviter's
    /// EOA (7702, after approving this escrow). Pulls exactly `amount`.
    function createInvitation(bytes32 inviteId, address token, uint256 amount) external nonReentrant whenNotPaused {
        require(_allowed(token), "token not allowed");
        require(amount > 0 && amount <= type(uint128).max, "bad amount");
        bytes32 key = invitationKey(msg.sender, inviteId);
        require(invitations[key].inviter == address(0), "invite exists");

        // Pull first, then record what actually arrived (defends against a
        // fee-on-transfer token, though neither allowed token is one).
        uint256 before = IERC20(token).balanceOf(address(this));
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = IERC20(token).balanceOf(address(this)) - before;
        require(received == amount, "unexpected transfer amount");

        invitations[key] = Invitation({
            inviter: msg.sender,
            token: token,
            amount: uint128(amount),
            expiresAt: uint64(block.timestamp) + RECLAIM_PERIOD,
            settled: false
        });
        emit InvitationCreated(inviteId, msg.sender, token, amount, uint64(block.timestamp) + RECLAIM_PERIOD);
    }

    // ═════════════════════════ Claim / Reclaim ══════════════════════════

    /// Release an unclaimed, unexpired invite to the recipient the backend
    /// verified. SPONSOR-authorized — the sponsor is the party that knows
    /// which joining user the phone/invite belongs to.
    function claimInvitation(
        bytes32 inviteId,
        address inviter,
        address recipient,
        bool recipientEligible,
        uint256 minAmountOut
    ) external onlySponsor nonReentrant whenNotPaused returns (uint256 amount) {
        Invitation storage inv = invitations[invitationKey(inviter, inviteId)];
        require(inv.inviter != address(0), "no invite");
        require(!inv.settled, "settled");
        require(block.timestamp <= inv.expiresAt, "expired");
        require(recipient != address(0) && recipient != address(this), "bad recipient");
        require(recipient != inv.inviter, "recipient is inviter");

        inv.settled = true;
        uint256 locked = inv.amount;
        address tokenOut = inv.token;
        if (inv.token == address(CUSD_PLUS) && !recipientEligible) {
            amount = CUSD_PLUS.unwrapToCusd(locked, minAmountOut, recipient);
            tokenOut = address(CUSD);
        } else if (inv.token == address(CUSD) && recipientEligible) {
            CUSD.forceApprove(address(CUSD_PLUS), locked);
            amount = CUSD_PLUS.wrapCusd(locked, minAmountOut, recipient);
            CUSD.forceApprove(address(CUSD_PLUS), 0);
            tokenOut = address(CUSD_PLUS);
        } else {
            require(minAmountOut == 0 || locked >= minAmountOut, "min out");
            amount = locked;
            IERC20(inv.token).safeTransfer(recipient, amount);
        }
        emit InvitationClaimed(inviteId, recipient, tokenOut, amount);
    }

    /// The inviter takes back an unclaimed invite after the reclaim window.
    /// NEVER pausable — an exit is always available.
    function reclaimInvitation(bytes32 inviteId) external nonReentrant returns (uint256 amount) {
        Invitation storage inv = invitations[invitationKey(msg.sender, inviteId)];
        require(inv.inviter == msg.sender, "not inviter");
        require(!inv.settled, "settled");
        require(block.timestamp > inv.expiresAt, "not expired");

        inv.settled = true;
        amount = inv.amount;
        IERC20(inv.token).safeTransfer(inv.inviter, amount);
        emit InvitationReclaimed(inviteId, inv.inviter, amount);
    }

    // ═════════════════════════ Admin (Safe) ═════════════════════════════

    function setSponsor(address sponsor_) external onlyOwner {
        require(sponsor_ != address(0), "zero sponsor");
        sponsor = sponsor_;
        emit SponsorSet(sponsor_);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// Disabled: renouncing while paused would strand claims (reclaim still
    /// works, but the Safe should always be able to operate the escrow).
    function renounceOwnership() public view override onlyOwner {
        revert("renounce disabled");
    }
}
