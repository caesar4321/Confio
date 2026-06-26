from algopy import Account, ARC4Contract, Asset, Global, Txn, UInt64, arc4, gtxn, itxn


class ConfioAyudaHumanitaria(ARC4Contract):
    """cUSD humanitarian aid vault.

    Donations are public cUSD asset transfers into the app account. Releases are
    admin/operator-triggered cUSD transfers to approved volunteers. Proof links
    are intentionally off-chain and added by the backend after the volunteer has
    bought and distributed supplies.
    """

    admin: Account
    release_operator: Account
    cusd_asset_id: UInt64
    total_donated: UInt64
    total_released: UInt64
    donation_count: UInt64
    release_count: UInt64
    paused: UInt64

    @arc4.abimethod(create='require')
    def create(self, cusd_asset_id: UInt64, admin: Account, release_operator: Account) -> None:
        self.admin = admin
        self.release_operator = release_operator
        self.cusd_asset_id = cusd_asset_id
        self.total_donated = UInt64(0)
        self.total_released = UInt64(0)
        self.donation_count = UInt64(0)
        self.release_count = UInt64(0)
        self.paused = UInt64(0)

    @arc4.abimethod()
    def opt_in_cusd(self) -> None:
        self._assert_admin()
        assert self.paused == UInt64(0)
        itxn.AssetTransfer(
            xfer_asset=Asset(self.cusd_asset_id),
            asset_receiver=Global.current_application_address,
            asset_amount=UInt64(0),
        ).submit()

    @arc4.abimethod()
    def donate(self, donation: gtxn.AssetTransferTransaction, donation_ref: arc4.String) -> None:
        assert self.paused == UInt64(0)
        assert donation.asset_receiver == Global.current_application_address
        assert donation.xfer_asset.id == self.cusd_asset_id
        assert donation.asset_amount > UInt64(0)
        self.total_donated += donation.asset_amount
        self.donation_count += UInt64(1)

    @arc4.abimethod()
    def release(self, recipient: Account, amount: UInt64, release_ref: arc4.String) -> None:
        self._assert_release_authorized()
        assert self.paused == UInt64(0)
        assert amount > UInt64(0)
        itxn.AssetTransfer(
            xfer_asset=Asset(self.cusd_asset_id),
            asset_receiver=recipient,
            asset_amount=amount,
        ).submit()
        self.total_released += amount
        self.release_count += UInt64(1)

    @arc4.abimethod()
    def pause(self) -> None:
        self._assert_admin()
        self.paused = UInt64(1)

    @arc4.abimethod()
    def unpause(self) -> None:
        self._assert_admin()
        self.paused = UInt64(0)

    @arc4.abimethod()
    def set_admin(self, new_admin: Account) -> None:
        self._assert_admin()
        self.admin = new_admin

    @arc4.abimethod()
    def set_release_operator(self, new_operator: Account) -> None:
        self._assert_admin()
        self.release_operator = new_operator

    @arc4.abimethod()
    def emergency_withdraw(self, recipient: Account, amount: UInt64) -> None:
        self._assert_admin()
        assert self.paused == UInt64(1)
        assert amount > UInt64(0)
        itxn.AssetTransfer(
            xfer_asset=Asset(self.cusd_asset_id),
            asset_receiver=recipient,
            asset_amount=amount,
        ).submit()

    @arc4.abimethod(allow_actions=["UpdateApplication"])
    def update(self) -> None:
        self._assert_admin()

    def _assert_admin(self) -> None:
        assert Txn.sender == self.admin

    def _assert_release_authorized(self) -> None:
        assert Txn.sender == self.admin or Txn.sender == self.release_operator
