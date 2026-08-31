// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "../CusdVault.sol";

contract CusdMockUsdt is ERC20 {
    constructor() ERC20("USDT", "USDT") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract CusdVaultV2 is CusdVault {
    constructor(address usdt) CusdVault(usdt) {}

    function version() external pure returns (uint256) {
        return 2;
    }
}

contract MockSavingsVault {}

contract CusdVaultTest is Test {
    CusdMockUsdt usdt;
    CusdVault vault;

    address treasury = makeAddr("treasury");
    address sponsor = makeAddr("sponsor");
    address savings;
    address user = makeAddr("user");
    address recipient = makeAddr("recipient");

    function setUp() public {
        savings = address(new MockSavingsVault());
        usdt = new CusdMockUsdt();
        CusdVault implementation = new CusdVault(address(usdt));
        vault = CusdVault(
            address(new ERC1967Proxy(address(implementation), abi.encodeCall(CusdVault.initialize, (treasury, 90))))
        );

        vm.startPrank(treasury);
        vault.setSponsor(sponsor, true);
        vault.setSavingsVault(savings);
        vm.stopPrank();

        usdt.mint(user, 1_000_000e18);
        vm.prank(user);
        usdt.approve(address(vault), type(uint256).max);
    }

    function _mint(address holder, uint256 gross) internal returns (uint256 net) {
        usdt.mint(holder, gross);
        vm.prank(holder);
        usdt.approve(address(vault), type(uint256).max);
        vm.prank(holder, sponsor);
        return vault.mintWithFee(gross, 0, holder);
    }

    function test_initializeAndPreview_usesCeilRounding() public view {
        assertEq(vault.name(), "Confio Dollar");
        assertEq(vault.symbol(), "cUSD");
        assertEq(vault.feeBps(), 90);
        assertEq(vault.feeFor(1), 1);
        assertEq(vault.feeFor(10_000), 90);
        (uint256 fee, uint256 net) = vault.previewMint(100e18);
        assertEq(fee, 0.9e18);
        assertEq(net, 99.1e18);
    }

    function test_mintWithFee_isSponsoredAndAccruesEntryFee() public {
        vm.prank(user, sponsor);
        uint256 out = vault.mintWithFee(100e18, 99.1e18, user);

        assertEq(out, 99.1e18);
        assertEq(vault.balanceOf(user), 99.1e18);
        assertEq(vault.accruedEntryFees(), 0.9e18);
        assertEq(usdt.balanceOf(address(vault)), 100e18);
        assertEq(vault.backingUsdt(), 99.1e18);
        assertTrue(vault.isFullyBacked());
    }

    function test_mintWithFee_rejectsUnsponsoredCaller() public {
        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        vault.mintWithFee(100e18, 0, user);
    }

    function test_mintWithFee_rejectsThirdPartyRecipientFromUserCall() public {
        vm.prank(user, sponsor);
        vm.expectRevert("recipient not caller");
        vault.mintWithFee(100e18, 0, recipient);
    }

    function test_redeemWithFee_isPermissionlessAndAccruesExitFee() public {
        uint256 minted = _mint(user, 100e18);
        uint256 before = usdt.balanceOf(recipient);

        vm.prank(user, user);
        uint256 out = vault.redeemWithFee(minted, 0, recipient);

        uint256 expectedFee = vault.feeFor(minted);
        assertEq(out, minted - expectedFee);
        assertEq(usdt.balanceOf(recipient) - before, out);
        assertEq(vault.balanceOf(user), 0);
        assertEq(vault.accruedExitFees(), expectedFee);
        assertTrue(vault.isFullyBacked());
    }

    function test_savingsRoundTrip_isFeeFreeAndRequiresSponsor() public {
        uint256 amount = _mint(user, 100e18);
        uint256 entryFeesBefore = vault.accruedEntryFees();

        vm.prank(user);
        vault.transfer(savings, amount);
        vm.prank(savings, sponsor);
        uint256 usdtOut = vault.redeemForSavings(amount, savings);
        assertEq(usdtOut, amount);

        vm.prank(savings);
        usdt.approve(address(vault), amount);
        vm.prank(savings, sponsor);
        uint256 cusdOut = vault.mintForSavings(amount, user);

        assertEq(cusdOut, amount);
        assertEq(vault.balanceOf(user), amount);
        assertEq(vault.accruedEntryFees(), entryFeesBefore);
        assertEq(vault.accruedExitFees(), 0);
        assertTrue(vault.isFullyBacked());
    }

    function test_savingsFeeFreePath_rejectsMissingSponsor() public {
        uint256 amount = _mint(user, 100e18);
        vm.prank(user);
        vault.transfer(savings, amount);

        vm.prank(savings, savings);
        vm.expectRevert("not sponsored");
        vault.redeemForSavings(amount, savings);
    }

    function test_settleSavingsEntry_chargesFeeWithoutChangingSupply() public {
        usdt.mint(savings, 100e18);
        vm.prank(savings);
        usdt.approve(address(vault), type(uint256).max);
        uint256 supplyBefore = vault.totalSupply();

        vm.prank(savings, sponsor);
        uint256 net = vault.settleSavingsEntry(100e18, 99.1e18);

        assertEq(net, 99.1e18);
        assertEq(usdt.balanceOf(savings), net);
        assertEq(vault.accruedEntryFees(), 0.9e18);
        assertEq(vault.totalSupply(), supplyBefore);
        assertTrue(vault.isFullyBacked());
    }

    function test_settleSavingsExit_isPermissionlessThroughSavingsVault() public {
        usdt.mint(savings, 100e18);
        vm.prank(savings);
        usdt.approve(address(vault), type(uint256).max);

        vm.prank(savings, savings);
        uint256 net = vault.settleSavingsExit(100e18, 0, recipient);

        assertEq(net, 99.1e18);
        assertEq(usdt.balanceOf(recipient), net);
        assertEq(vault.accruedExitFees(), 0.9e18);
        assertTrue(vault.isFullyBacked());
    }

    function test_collectFees_onlyUsesExplicitCounters() public {
        _mint(user, 100e18);
        usdt.mint(address(vault), 50e18); // donation is not fee revenue

        uint256 before = usdt.balanceOf(treasury);
        vm.prank(treasury);
        vault.collectFees(0.9e18, 0);

        assertEq(usdt.balanceOf(treasury) - before, 0.9e18);
        assertEq(vault.accruedEntryFees(), 0);
        assertTrue(vault.isFullyBacked());

        vm.prank(treasury);
        vm.expectRevert("entry exceeds accrued");
        vault.collectFees(1, 0);
    }

    function test_rescueSurplus_onlyWithdrawsDirectDonation() public {
        _mint(user, 100e18);
        usdt.mint(address(vault), 50e18);

        assertEq(vault.surplusUsdt(), 50e18);
        vm.prank(treasury);
        vm.expectRevert("exceeds surplus");
        vault.rescueSurplusUsdt(50e18 + 1);

        uint256 before = usdt.balanceOf(treasury);
        vm.prank(treasury);
        vault.rescueSurplusUsdt(50e18);
        assertEq(usdt.balanceOf(treasury) - before, 50e18);
        assertEq(vault.surplusUsdt(), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);
        assertTrue(vault.isFullyBacked());
    }

    function test_setSavingsVault_rejectsEoa() public {
        vm.prank(treasury);
        vm.expectRevert("savings vault not contract");
        vault.setSavingsVault(makeAddr("not-a-contract"));
    }

    function test_feeCannotExceedImmutableMaximum() public {
        vm.prank(treasury);
        vm.expectRevert("fee too high");
        vault.setFeeBps(91);

        vm.prank(treasury);
        vault.setFeeBps(0);
        assertEq(vault.feeFor(100e18), 0);
    }

    function test_pauseStopsTransfersMintAndRedeem() public {
        uint256 amount = _mint(user, 100e18);
        vm.prank(treasury);
        vault.pause();

        vm.prank(user);
        vm.expectRevert("Pausable: paused");
        vault.transfer(recipient, 1e18);

        vm.prank(user, sponsor);
        vm.expectRevert();
        vault.mintWithFee(1e18, 0, user);

        vm.prank(user);
        vm.expectRevert();
        vault.redeemWithFee(amount, 0, recipient);
    }

    function test_ownerCanUpgradeWithoutChangingState() public {
        _mint(user, 100e18);
        CusdVaultV2 v2 = new CusdVaultV2(address(usdt));

        vm.prank(treasury);
        vault.upgradeToAndCall(address(v2), "");

        assertEq(CusdVaultV2(address(vault)).version(), 2);
        assertEq(vault.balanceOf(user), 99.1e18);
        assertEq(vault.accruedEntryFees(), 0.9e18);
        assertEq(vault.savingsVault(), savings);
    }

    function test_renounceOwnership_isDisabled() public {
        vm.prank(treasury);
        vm.expectRevert("renounce disabled");
        vault.renounceOwnership();
        assertEq(vault.owner(), treasury);
    }

    function testFuzz_feeCeilAndRoundTripBacking(uint96 rawGross) public {
        // Both entry and exit use ceiling-rounded fees. At gross=2 the
        // entry leaves one wei, whose exit fee consumes the entire amount;
        // that is deliberately rejected by the vault as a dust conversion.
        uint256 gross = bound(uint256(rawGross), 3, 1_000_000e18);
        uint256 expectedFee = (gross * 90 + 9_999) / 10_000;
        assertEq(vault.feeFor(gross), expectedFee);

        uint256 minted = _mint(user, gross);
        assertEq(minted, gross - expectedFee);
        assertTrue(vault.isFullyBacked());

        vm.prank(user, user);
        uint256 redeemed = vault.redeemWithFee(minted, 0, recipient);
        assertEq(redeemed, minted - ((minted * 90 + 9_999) / 10_000));
        assertEq(vault.totalSupply(), 0);
        assertTrue(vault.isFullyBacked());
        assertEq(usdt.balanceOf(address(vault)), vault.accruedEntryFees() + vault.accruedExitFees());
    }
}
