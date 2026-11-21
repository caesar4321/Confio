// Screens using the 2026-11-20 SDL additions, with their older-server
// fallbacks; the funnel's client stages; and the beneficiary's direct
// (serverless) claim entry point.
import { nav, rememberedDirect, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import Clipboard from '@react-native-clipboard/clipboard';
import * as service from '../../services/smartAccount';
import * as direct from '../../services/smartAccountDirect';
import { logSmartAccountFunnel } from '../../services/paidOffers';
import {
  account, beneficiary, designation, failedRead, flush, hasTappable, movePreview, offer, ok, prepared, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { BeneficiarySetupScreen, riskDisclosureLines, residualRiskLines } from '../BeneficiarySetupScreen';
import { BeneficiaryStatusScreen } from '../BeneficiaryStatusScreen';
import { SmartAccountHomeScreen } from '../SmartAccountHomeScreen';
import { SmartAccountOfferScreen } from '../SmartAccountOfferScreen';
import { SmartAccountFundScreen } from '../SmartAccountFundScreen';
import { BeneficiaryClaimScreen } from '../BeneficiaryClaimScreen';
import { BeneficiaryClaimStatusScreen } from '../BeneficiaryClaimStatusScreen';

const api = service as jest.Mocked<typeof service>;
const glue = direct as jest.Mocked<typeof direct>;
let tree: renderer.ReactTestRenderer;
const mount = async (el: React.ReactElement) => {
  await act(async () => { tree = renderer.create(el); });
  await flush();
};
const ACCOUNT = '0x00000000000000000000000000000000000000aa';
const ME = '0x19e7e376e7c213b7e7e7e46cc70a5dd086daff2a';

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccount.mockResolvedValue(ok(account()));
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchSmartAccountBeneficiaryEnabled.mockResolvedValue(ok(true));
  api.fetchBeneficiaryRiskDisclosure.mockResolvedValue(ok([]));
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview()));
  api.fetchSmartAccountEntry.mockResolvedValue(ok(null));
  api.prepareBeneficiaryWindowChange.mockResolvedValue(prepared());
  api.prepareSmartAccountSubscribe.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

describe('beneficiaryRiskDisclosure', () => {
  it('fills {name} and {days} into the server sentences', () => {
    expect(riskDisclosureLines(['Si {name} inicia un reclamo, tienes {days} días.', '{name} y {name}.'], 'Ana P.', 90))
      .toEqual(['Si Ana P. inicia un reclamo, tienes 90 días.', 'Ana P. y Ana P..']);
  });

  it('falls back to the app copy when the server sends nothing', () => {
    expect(riskDisclosureLines([], 'Ana', 180)).toEqual(residualRiskLines('Ana', 180));
    expect(riskDisclosureLines(undefined, 'Ana', 180)).toEqual(residualRiskLines('Ana', 180));
  });

  it('shows the server wording on the setup screen', async () => {
    api.fetchBeneficiaryRiskDisclosure.mockResolvedValue(ok(['Si no firmas nada durante los {days} días, {name} recibe la cuenta.']));
    setRouteParams({ handle: 'ana', name: 'Ana P.' });
    await mount(<BeneficiarySetupScreen />);
    expect(text(tree)).toContain('Si no firmas nada durante los 180 días, Ana P. recibe la cuenta.');
    expect(text(tree)).not.toContain(residualRiskLines('Ana P.', 180)[0]);
  });

  it('keeps the app copy on an older server', async () => {
    api.fetchBeneficiaryRiskDisclosure.mockResolvedValue(failedRead);
    setRouteParams({ handle: 'ana', name: 'Ana P.' });
    await mount(<BeneficiarySetupScreen />);
    expect(text(tree)).toContain(residualRiskLines('Ana P.', 180)[0]);
  });
});

describe('Cambiar plazo', () => {
  it('signs a window change and says the person accepts again', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary() })));
    await mount(<BeneficiaryStatusScreen />);
    await tap(tree, 'status-change-window');
    expect(text(tree)).toContain('Ana P. tendrá que aceptar de nuevo. Hasta que acepte, sigue valiendo el plazo de 180 días.');
    await tap(tree, '365 días');
    await tap(tree, 'window-accept');
    await tap(tree, 'window-review');
    await flush();
    expect(api.prepareBeneficiaryWindowChange).toHaveBeenCalledWith(365);
    expect(api.prepareBeneficiaryDesignation).not.toHaveBeenCalled();
    expect(text(tree)).toContain('tendrá que aceptar de nuevo');
    await tap(tree, 'sign-confirm');
    await flush();
    expect(api.signAndSubmitPrepared).toHaveBeenCalled();
  });

  it('shows the residual risk for the NEW window and requires acceptance before preparing', async () => {
    api.fetchBeneficiaryRiskDisclosure.mockResolvedValue(ok(['Si no firmas nada durante los {days} días, {name} recibe la cuenta.']));
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary() })));
    await mount(<BeneficiaryStatusScreen />);
    await tap(tree, 'status-change-window');
    await tap(tree, '365 días');
    expect(text(tree)).toContain('Si no firmas nada durante los 365 días, Ana P. recibe la cuenta.');
    await tap(tree, 'window-review');
    await flush();
    expect(text(tree)).toContain('Marca la casilla para continuar.');
    expect(api.prepareBeneficiaryWindowChange).not.toHaveBeenCalled();
    // Accepting one window, then picking another, asks again.
    await tap(tree, 'window-accept');
    await tap(tree, '90 días');
    expect(text(tree)).toContain('Si no firmas nada durante los 90 días, Ana P. recibe la cuenta.');
    await tap(tree, 'window-review');
    await flush();
    expect(api.prepareBeneficiaryWindowChange).not.toHaveBeenCalled();
    await tap(tree, 'window-accept');
    await tap(tree, 'window-review');
    await flush();
    expect(api.prepareBeneficiaryWindowChange).toHaveBeenCalledWith(90);
  });

  it('falls back to the app copy for the new window on an older server', async () => {
    api.fetchBeneficiaryRiskDisclosure.mockResolvedValue(failedRead);
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary() })));
    await mount(<BeneficiaryStatusScreen />);
    await tap(tree, 'status-change-window');
    await tap(tree, '365 días');
    expect(text(tree)).toContain(residualRiskLines('Ana P.', 365)[0]);
  });

  it('only offers windows other than the current one', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary(), windowOptionsDays: [180] })));
    await mount(<BeneficiaryStatusScreen />);
    expect(hasTappable(tree, 'status-change-window')).toBe(false);
    expect(hasTappable(tree, 'status-change')).toBe(true);
  });
});

describe('SmartAccount.beneficiaryEnabled on the home', () => {
  it('uses the account flag and does not need the offer', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ beneficiaryEnabled: false })));
    await mount(<SmartAccountHomeScreen />);
    expect(hasTappable(tree, 'home-beneficiary')).toBe(true);
    expect(api.fetchSmartAccountOffer).not.toHaveBeenCalled();
  });

  it('hides the row when the account flag says no', async () => {
    api.fetchSmartAccountBeneficiaryEnabled.mockResolvedValue(ok(false));
    await mount(<SmartAccountHomeScreen />);
    expect(hasTappable(tree, 'home-beneficiary')).toBe(false);
  });

  it('falls back to the offer on an older server', async () => {
    api.fetchSmartAccountBeneficiaryEnabled.mockResolvedValue(failedRead);
    await mount(<SmartAccountHomeScreen />);
    expect(api.fetchSmartAccountOffer).toHaveBeenCalled();
    expect(hasTappable(tree, 'home-beneficiary')).toBe(true);
  });
});

describe('funnel', () => {
  it('logs subscribe_opened when the offer opens', async () => {
    await mount(<SmartAccountOfferScreen />);
    expect(logSmartAccountFunnel).toHaveBeenCalledWith('subscribe_opened');
    expect(logSmartAccountFunnel).toHaveBeenCalledTimes(1);
  });

  it('logs subscribe_signed only after the subscribe batch executes', async () => {
    setRouteParams({ plan: 'annual' });
    api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
      assets: [{ key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null }],
    })));
    await mount(<SmartAccountFundScreen />);
    await tap(tree, 'fund-review');
    await flush();
    expect(logSmartAccountFunnel).not.toHaveBeenCalled();
    await tap(tree, 'sign-confirm');
    await flush();
    expect(logSmartAccountFunnel).toHaveBeenCalledWith('subscribe_signed', 'annual');
  });

  it('does not log subscribe_signed when the signature does not go through', async () => {
    setRouteParams({ plan: 'annual' });
    api.signAndSubmitPrepared.mockResolvedValue({ status: 'not_sent', code: 'x' });
    await mount(<SmartAccountFundScreen />);
    await tap(tree, 'fund-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    expect(logSmartAccountFunnel).not.toHaveBeenCalled();
  });
});

describe('direct claim (spec 6.7)', () => {
  const active = (over = {}) => designation({
    state: 'active', acceptedAt: '2026-11-12T12:00:00Z', expiresAt: null, contractAddress: ACCOUNT,
    chainName: 'BNB Smart Chain', canClaim: true, ...over,
  });
  const situation = (over: Partial<direct.DirectSituation> = {}): direct.DirectSituation => ({
    me: ME, account: ACCOUNT, step: { kind: 'initiate' }, holdings: [], gas: { kind: 'enough' }, ...over,
  });

  beforeEach(() => {
    setRouteParams({ designationId: 'd1' });
    glue.loadDirectEntry.mockResolvedValue({ account: ACCOUNT, designationId: 'd1', savedAt: 1 });
    glue.ownWalletAddress.mockResolvedValue(ME);
    glue.readDirectSituation.mockResolvedValue(situation());
    glue.runDirectStep.mockResolvedValue({ status: 'executed', done: 1, total: 1 });
  });

  it('keeps the account address on the device when designations load', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([active()]));
    await mount(<BeneficiaryClaimScreen />);
    expect(rememberedDirect).toContainEqual(expect.objectContaining({
      account: ACCOUNT, designationId: 'd1', ownerName: 'Luis R.', chainName: 'BNB Smart Chain',
    }));
  });

  it('is offered plainly when Confío cannot be reached, and sends without the server', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimScreen />);
    expect(text(tree)).toContain('No pudimos conectar con Confío');
    await tap(tree, 'direct-offer');
    await flush();
    expect(glue.loadDirectEntry).toHaveBeenCalledWith({ designationId: 'd1' });
    expect(text(tree)).toContain('Pedir la cuenta');
    await tap(tree, 'direct-send');
    await flush();
    expect(glue.runDirectStep).toHaveBeenCalledWith(situation());
    expect(api.prepareBeneficiaryClaim).not.toHaveBeenCalled();
    expect(text(tree)).toContain('Tu pedido quedó en la red');
  });

  it('sits behind a help disclosure while the server works', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([active()]));
    await mount(<BeneficiaryClaimScreen />);
    expect(hasTappable(tree, 'direct-open')).toBe(false);
    await tap(tree, 'direct-help');
    await tap(tree, 'direct-open');
    await flush();
    expect(glue.readDirectSituation).toHaveBeenCalled();
  });

  it('says plainly that BNB is needed and shows the own address to receive it', async () => {
    glue.readDirectSituation.mockResolvedValue(situation({ gas: { kind: 'short', needBnb: '0.00001' } }));
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimStatusScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    const out = text(tree);
    expect(out).toContain('Necesitas un poco de BNB');
    expect(out).toContain('Envía al menos 0.00001 BNB por la red BNB Smart Chain a tu billetera');
    expect(out).toContain(ME);
    expect(hasTappable(tree, 'direct-send')).toBe(false);
    await tap(tree, 'direct-copy');
    expect(Clipboard.setString).toHaveBeenCalledWith(ME);
  });

  it('offers to receive the account once the window is over', async () => {
    glue.readDirectSituation.mockResolvedValue(situation({ step: { kind: 'execute' } }));
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimStatusScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    expect(text(tree)).toContain('Firmar y recibir la cuenta');
  });

  it('shows the contract refusal instead of a button', async () => {
    glue.readDirectSituation.mockResolvedValue(situation({ gas: { kind: 'refused', error: 'Cooldown' } }));
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    expect(text(tree)).toContain('Todavía no puedes pedirla de nuevo');
    expect(hasTappable(tree, 'direct-send')).toBe(false);
  });

  it('says so when this phone never saw the account address', async () => {
    glue.loadDirectEntry.mockResolvedValue(null);
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    expect(text(tree)).toContain('no tiene guardada la dirección de la cuenta');
  });

  it('never calls an outcome it did not see a failure', async () => {
    glue.runDirectStep.mockResolvedValue({ status: 'unknown', done: 0, total: 1 });
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    await tap(tree, 'direct-send');
    await flush();
    expect(text(tree)).toContain('Estamos confirmando');
    expect(nav.navigate).not.toHaveBeenCalled();
  });

  it('on a multi-asset withdraw with an unseen verdict, says to wait and check before repeating', async () => {
    glue.readDirectSituation.mockResolvedValue(situation({
      step: { kind: 'withdraw' },
      holdings: [
        { address: '0x' + '11'.repeat(20), label: 'Confío Dollar', balance: 1n },
        { address: '0x' + '22'.repeat(20), label: 'Oro', balance: 1n },
        { address: '0x' + '33'.repeat(20), label: 'Bitcoin', balance: 1n },
      ],
    }));
    glue.runDirectStep.mockResolvedValue({ status: 'unknown', done: 1, total: 3 });
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryClaimScreen />);
    await tap(tree, 'direct-offer');
    await flush();
    await tap(tree, 'direct-send');
    await flush();
    const out = text(tree);
    expect(out).toContain('Ya se movieron 1 de 3');
    expect(out).toContain('revisa de nuevo antes de repetirla');
    expect(out).not.toContain('No se movió nada');
    expect(hasTappable(tree, 'direct-unknown-recheck')).toBe(true);
  });
});
