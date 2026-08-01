import React, { useState, useEffect, useMemo } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    TextInput,
    ActivityIndicator,
    Alert,
    ScrollView,
    Platform,
    Linking,
    Image,
    StatusBar,
} from 'react-native';
import { Header } from '../navigation/Header';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { colors } from '../config/theme';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useNavigation, useFocusEffect, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import GuardarianLogo from '../assets/svg/guardarian.svg';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useCountry } from '../contexts/CountryContext';
import { gql, useLazyQuery, useMutation, useQuery } from '@apollo/client';
import { getCurrencyForCountry } from '../utils/currencyMapping';
import { getCountryByIso } from '../utils/countries';
import { createGuardarianTransaction, fetchGuardarianFiatCurrencies, GuardarianFiatCurrency } from '../services/guardarianService';
import { GET_PENDING_RAMP_TRANSACTION } from '../apollo/queries';
import USDCLogo from '../assets/png/USDC.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import PreFlightModal from '../components/PreFlightModal';
import GuardarianReturnModal from '../components/GuardarianReturnModal';
import { technicalFontFamily } from '../utils/fontFamily';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { requestRampCriticalAuth } from '../utils/rampFlow';
import { getVaultShares, redeemSavingsToUsdt } from '../services/cusdPlusVault';
import { getActiveEvmWallet } from '../services/secureDeterministicWallet';
import algorandService from '../services/algorandService';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'Sell'>;

// Savings off-ramp needs the vault (proxy) address; served, never hardcoded.
const SAVINGS_SELL_PARAMS = gql`
  query GuardarianSavingsSellParams {
    cusdPlusConvertParams {
      vaultAddress
    }
  }
`;

const SUBMIT_AUTO_SWAP_FOR_OFFRAMP = gql`
  mutation SubmitAutoSwapTransactions(
    $internalId: String!
    $signedTransactions: [String]!
    $sponsorTransactions: [String]!
    $withdrawalId: String
  ) {
    submitAutoSwapTransactions(
      internalId: $internalId
      signedTransactions: $signedTransactions
      sponsorTransactions: $sponsorTransactions
      withdrawalId: $withdrawalId
    ) {
      success
      error
      txid
    }
  }
`;

// Server-destination Guardarian sell send: the deposit address is re-fetched
// from Guardarian inside the mutation — never supplied (or editable) here.
const BUILD_GUARDARIAN_OFFRAMP = gql`
  mutation BuildGuardarianOfframpTransactions {
    buildGuardarianOfframpTransactions {
      success
      error
      transactions
    }
  }
`;

const parseSwapPayload = (raw: any): any => {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return {}; }
  }
  return raw;
};

export const SellScreen = () => {
    const navigation = useNavigation<NavigationProp>();
    const route = useRoute<any>();
    const { userProfile } = useAuth() as any;
    const { activeAccount } = useAccount();
    const { selectedCountry, userCountry } = useCountry();

    // cUSD+ savings mode: sell USDT-BSC straight from the savings vault
    // (redeemToUsdt pays Guardarian's deposit address — no intermediate hop).
    // Default mode sells USDC-Algorand from the day-to-day balance.
    const isSavings = route.params?.destination === 'cusd_plus';
    const { savings, usdtBalanceUsd } = useSavingsPortfolio();
    const savingsBalanceUsd = savings?.balanceUsd ?? 0;
    // Ondo-ineligible users hold the plain dollar as RAW USDT and never mint
    // vault shares — their money must still reach a bank. max(), not sum:
    // one withdrawal moves ONE leg (redeem shares, or transfer USDT), so
    // summing would promise a figure no single operation can deliver.
    const rawUsdtUsd = usdtBalanceUsd ?? 0;
    const withdrawableUsd = Math.max(savingsBalanceUsd, rawUsdtUsd);
    // Copy has to match the product the money actually IS. An Ondo-ineligible
    // user holds plain Confío Dollar (USDT) and has no vault at all, so
    // "ahorro"/"bóveda" would be a lie on every screen of this flow.
    const isYieldUser = Boolean(savings?.enabled);
    const balanceNoun = isYieldUser ? 'ahorro' : 'saldo';
    const { data: savingsParamsData } = useQuery(SAVINGS_SELL_PARAMS, { skip: !isSavings });
    const vaultAddress: string = savingsParamsData?.cusdPlusConvertParams?.vaultAddress || '';
    const [sendingFromSavings, setSendingFromSavings] = useState(false);
    const sellTicker = isSavings ? 'USDT' : 'USDC';

    const [buildGuardarianOfframp] = useMutation(BUILD_GUARDARIAN_OFFRAMP);
    const [submitAutoSwapForOfframp] = useMutation(SUBMIT_AUTO_SWAP_FOR_OFFRAMP);
    const [guardarianSendBusy, setGuardarianSendBusy] = useState(false);

    // Sign every txn in a build payload with the user's key and submit the group.
    const signAndSubmitGroup = async (payload: any): Promise<void> => {
        const { Buffer } = require('buffer');
        const unsigned: string[] = payload.transactions || [];
        if (!unsigned.length || !payload.internal_id) {
            throw new Error('No recibimos las transacciones para firmar.');
        }
        const signed = await Promise.all(
            unsigned.map(async (b64: string) => {
                const bytes = Uint8Array.from(Buffer.from(b64, 'base64'));
                const signedBytes = await algorandService.signTransactionBytes(bytes);
                return Buffer.from(signedBytes).toString('base64');
            })
        );
        const sponsors = (payload.sponsor_transactions || []).map((s: any) =>
            typeof s === 'string' ? s : JSON.stringify(s)
        );
        const res = await submitAutoSwapForOfframp({
            variables: {
                internalId: payload.internal_id,
                signedTransactions: signed,
                sponsorTransactions: sponsors,
                withdrawalId: payload.withdrawal_id ? String(payload.withdrawal_id) : undefined,
            },
        });
        const d = res.data?.submitAutoSwapTransactions;
        if (!d?.success) {
            throw new Error(d?.error || 'No se pudo enviar la transacción.');
        }
    };

    // Default to user's local currency if available
    const derivedCurrencyCode = useMemo(() => {
        let localCurrency = 'USD';

        if (userProfile?.phoneCountry) {
            const country = getCountryByIso(userProfile.phoneCountry);
            if (country) localCurrency = getCurrencyForCountry(country as any);
        } else if (selectedCountry) {
            localCurrency = getCurrencyForCountry(selectedCountry as any);
        } else if (userCountry) {
            localCurrency = getCurrencyForCountry(userCountry as any);
        }

        return localCurrency;
    }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

    const [amount, setAmount] = useState('');
    const [currencyCode, setCurrencyCode] = useState(derivedCurrencyCode);
    const [loading, setLoading] = useState(false);
    const [fiatOptions, setFiatOptions] = useState<GuardarianFiatCurrency[]>([]);
    const [payoutFiats, setPayoutFiats] = useState<string[]>([]);
    const [fiatLoading, setFiatLoading] = useState(false);
    const [fiatError, setFiatError] = useState<string | null>(null);
    const [showPreFlightModal, setShowPreFlightModal] = useState(false);
    const [showGuardarianReturnModal, setShowGuardarianReturnModal] = useState(false);
    const [awaitingGuardarianReturn, setAwaitingGuardarianReturn] = useState(false);
    const [loadPendingRampTransaction] = useLazyQuery(GET_PENDING_RAMP_TRANSACTION, {
        fetchPolicy: 'network-only',
    });

    useFocusEffect(
        React.useCallback(() => {
            let active = true;
            const checkPendingGuardarianRamp = async () => {
                if (awaitingGuardarianReturn) {
                    setShowGuardarianReturnModal(true);
                    return;
                }
                try {
                    const { data } = await loadPendingRampTransaction({
                        variables: {
                            provider: 'guardarian',
                            direction: 'off_ramp',
                        },
                    });
                    if (!active) return;
                    const pendingRamp = data?.pendingRampTransaction;
                    if (pendingRamp?.providerOrderId) {
                        setShowGuardarianReturnModal(true);
                    } else {
                        setShowGuardarianReturnModal(false);
                    }
                } catch (e) {
                }
            };

            checkPendingGuardarianRamp();
            return () => {
                active = false;
            };
        }, [awaitingGuardarianReturn, loadPendingRampTransaction])
    );

    // Order state
    const [orderCreated, setOrderCreated] = useState(false);
    const [depositAddress, setDepositAddress] = useState('');
    const [depositMemo, setDepositMemo] = useState('');
    const [orderId, setOrderId] = useState<number | undefined>(undefined);

    // Whitelist of currencies that Guardarian supports for sells.
    // Based on testing and Guardarian's API limitations.
    const SELL_SUPPORTED = ['EUR', 'MXN', 'CLP', 'COP', 'ARS', 'BRL'];
    const isCountrySupportedForSell = SELL_SUPPORTED.includes(derivedCurrencyCode);

    useEffect(() => {
        const pickDefaultPayout = (): { code: string; fallback: boolean } => {
            if (SELL_SUPPORTED.includes(derivedCurrencyCode)) return { code: derivedCurrencyCode, fallback: false };
            return { code: 'EUR', fallback: true };
        };

        const loadFiats = async () => {
            setFiatLoading(true);
            setFiatError(null);
            try {
                const fiatsRes = await fetchGuardarianFiatCurrencies();
                setFiatOptions(fiatsRes || []);

                // Hardcode supported list; prefer local if supported, else EUR.
                const { code, fallback } = pickDefaultPayout();
                setCurrencyCode(code);
                setPayoutFiats(SELL_SUPPORTED);
                if (fallback) {
                    setFiatError('Guardarian no soporta ventas en tu moneda. Usaremos EUR como predeterminado.');
                }

            } catch (err: any) {
                setFiatError('No pudimos cargar monedas disponibles para la venta. Usaremos EUR.');
                setCurrencyCode('EUR');
                setPayoutFiats(SELL_SUPPORTED);
            } finally {
                setFiatLoading(false);
            }
        };
        loadFiats();
    }, [derivedCurrencyCode]);

    const handleCreateOrder = async () => {
        const parsedAmount = parseFloat(amount);
        if (!amount.trim() || isNaN(parsedAmount) || parsedAmount <= 0) {
            Alert.alert('Monto inválido', 'Ingresa un monto mayor a 0.');
            return;
        }
        if (isSavings && parsedAmount > withdrawableUsd) {
            Alert.alert(
                'Saldo insuficiente',
                `Tu saldo disponible es $${withdrawableUsd.toFixed(2)}.`,
            );
            return;
        }

        // Show modal instruction first
        setShowPreFlightModal(true);
    };

    const handleProceedToGuardarian = async () => {
        setShowPreFlightModal(false);
        const parsedAmount = parseFloat(amount);
        setLoading(true);
        try {

            const tx = await createGuardarianTransaction({
                amount: parsedAmount,
                fromCurrency: sellTicker,
                // USDC sells: server defaults the network to ALGO.
                // Savings sells are USDT and must pin BSC explicitly.
                fromNetwork: isSavings ? 'BSC' : undefined,
                toCurrency: currencyCode,
                email: userProfile?.email,
                customerCountry: userProfile?.phoneCountry,
                externalId: `confio-${isSavings ? 'ahorro-sell' : 'sell'}-${Date.now()}`,
            });

            if (tx.deposit_address) {
                setDepositAddress(tx.deposit_address);
                setDepositMemo(tx.deposit_extra_id || '');
                setOrderId(tx.id);
                setOrderCreated(true);

                if (tx.redirect_url) {
                    setAwaitingGuardarianReturn(true);
                    await Linking.openURL(tx.redirect_url);
                }
                return;
            } else if (tx.redirect_url) {
                // Case: No address returned (yet), but we have a redirect URL (common for ARS/KYC required)
                // We don't show the "Order Created" screen because we have no address to show.
                // We just send the user to Guardarian.

                setAwaitingGuardarianReturn(true);
                await Linking.openURL(tx.redirect_url);
                return;
            } else {
                throw new Error('Guardarian no devolvió métodos de pago para la venta. Prueba otra moneda o intenta más tarde.');
            }

        } catch (err: any) {
            const msg = String(err?.message || '').toLowerCase();
            if (msg.includes('payout')) {
                setFiatError('Guardarian no ofrece métodos de pago para esta moneda/país. Prueba otra moneda o cambia de país.');
                setCurrencyCode('');
                Alert.alert(
                    'Sin métodos de pago',
                    'Guardarian no puede pagarte en esta moneda en tu país. Cambia de moneda y vuelve a intentar.'
                );
            } else {
                Alert.alert('Error', err.message || 'No se pudo crear la orden.');
            }
        } finally {
            setLoading(false);
        }
    };

    const handleCopyAddress = () => {
        Clipboard.setString(depositAddress);
        Alert.alert('Copiado', 'Dirección copiada al portapapeles');
    };

    // Auto-send for the Guardarian sell (cUSD rail): the server re-fetches the
    // deposit address and burns cUSD→USDC→sends it in one atomic group; the
    // user only confirms with biometrics — the destination stays server-side.
    const handleAutoSendToGuardarian = async () => {
        const parsedAmount = parseFloat(amount);
        const authenticated = await requestRampCriticalAuth({
            amount: Number.isFinite(parsedAmount) ? parsedAmount : 0,
            assetLabel: 'USDC',
            actionLabel: 'retiro',
        });
        if (!authenticated) {
            return;
        }
        setGuardarianSendBusy(true);
        try {
            const buildRes = await buildGuardarianOfframp();
            const build = buildRes.data?.buildGuardarianOfframpTransactions;
            if (!build?.success) {
                if (build?.error === 'no_pending_offramp') {
                    throw new Error('Tu orden de Guardarian expiró o ya se completó. Crea la venta de nuevo.');
                }
                if (build?.error === 'requires_app_optin') {
                    throw new Error('Tu cuenta necesita activarse para cUSD. Abre la app de nuevo e intenta.');
                }
                throw new Error(build?.error || 'No se pudo preparar el envío.');
            }
            await signAndSubmitGroup(parseSwapPayload(build.transactions));
            Alert.alert(
                'Enviado a Guardarian',
                'Tus fondos van en camino. Guardarian depositará en tu banco al confirmarlos.',
            );
            navigation.navigate('RampHistory', { initialFilter: 'off_ramp' });
        } catch (err: any) {
            Alert.alert('No se pudo enviar', err?.message || 'Intenta de nuevo.');
        } finally {
            setGuardarianSendBusy(false);
        }
    };

    // Savings sell: burn vault shares and have the vault pay USDT-BSC to
    // Guardarian's deposit address directly (redeemToUsdt recipient arg).
    const handleSendFromSavings = async () => {
        const parsedAmount = parseFloat(amount);
        if (!depositAddress || !Number.isFinite(parsedAmount) || parsedAmount <= 0) {
            return;
        }
        // No vault address is only fatal when there's nothing else to send:
        // an Ondo-ineligible user has no vault at all, and their raw USDT
        // withdrawal never touches one.
        if (!vaultAddress && !(rawUsdtUsd > 0)) {
            Alert.alert('Error', 'No pudimos cargar tu bóveda de ahorro. Cierra y vuelve a intentar.');
            return;
        }
        const authenticated = await requestRampCriticalAuth({
            amount: parsedAmount,
            assetLabel: 'US$ (ahorro)',
            actionLabel: 'retiro',
        });
        if (!authenticated) {
            return;
        }
        setSendingFromSavings(true);
        try {
            const wallet = await getActiveEvmWallet();
            const shares = vaultAddress
                ? await getVaultShares(vaultAddress, wallet.address)
                : 0n;
            // Two legs, one withdrawal. Vault shares are the yield position;
            // raw USDT is what Ondo-ineligible users hold (and what an
            // eligible user's deposit looks like before it mints). Pick the
            // leg on a STRICT comparison: an epsilon here would let a $10.01
            // order pick a $10.00 vault and then fund only $10.00, so the
            // order and the transfer would disagree by up to a cent.
            const useVault = shares > 0n && savingsBalanceUsd > 0
                && parsedAmount <= savingsBalanceUsd;
            if (!useVault && !(rawUsdtUsd > 0)) {
                throw new Error(`No tienes ${balanceNoun} disponible para retirar.`);
            }
            if (useVault) {
                // Proportional share slice; a near-full amount redeems
                // everything so rounding dust never strands in the vault.
                // Safe in this direction only: it sends slightly MORE than
                // the order, never less.
                const sharesToRedeem = parsedAmount >= savingsBalanceUsd - 0.01
                    ? shares
                    : (shares * BigInt(Math.round(parsedAmount * 1e6)))
                        / BigInt(Math.round(savingsBalanceUsd * 1e6));
                if (sharesToRedeem <= 0n) {
                    throw new Error('El monto es demasiado pequeño.');
                }
                // USDT-BSC is 18 decimals; floor the payout 1% under the quote.
                const minUsdtOut = BigInt(Math.round(parsedAmount * 0.99 * 1e6)) * 10n ** 12n;
                await redeemSavingsToUsdt({
                    vaultAddress,
                    shares: sharesToRedeem,
                    minUsdtOut,
                    recipient: depositAddress,
                    wallet,
                });
            } else {
                // LIVE balance, not the cached display figure: cusdPlusSummary
                // is explicitly display-grade, and funding an order off a stale
                // or cent-rounded number either underpays Guardarian or reverts
                // on-chain AFTER the order exists. Same pattern SendUsdtScreen
                // uses before an exact transfer.
                const { transferUsdt, USDT_BSC } = await import('../services/cusdPlusVault');
                const { selector, encodeAddress, bscEthCall } = await import('../services/evmWallet');
                const balHex = await bscEthCall(
                    USDT_BSC,
                    selector('balanceOf(address)') + encodeAddress(wallet.address),
                );
                const balWei = BigInt(balHex === '0x' ? '0x0' : balHex);
                // SIX decimals scaled to 18dp — the grain the Guardarian
                // order was created at. Cent rounding here would send a
                // different amount than the order says (the vault leg above
                // already uses 1e6 for exactly this reason).
                let amountWei = BigInt(Math.round(parsedAmount * 1e6)) * 10n ** 12n;
                if (amountWei > balWei) {
                    // Only a sub-cent shortfall is dust to absorb; anything
                    // larger means the order was quoted against money that
                    // isn't there, so refuse instead of underfunding it.
                    if (amountWei - balWei > 10n ** 16n) {
                        throw new Error(
                            `Tu saldo disponible es $${(Number(balWei / 10n ** 14n) / 100).toFixed(2)}.`,
                        );
                    }
                    amountWei = balWei;
                }
                if (amountWei <= 0n) {
                    throw new Error('El monto es demasiado pequeño.');
                }
                await transferUsdt({ to: depositAddress, amountWei, wallet });
            }
            Alert.alert(
                `Enviado desde tu ${balanceNoun}`,
                'Guardarian recibirá tus fondos en unos minutos y depositará en tu banco. Puedes seguir el estado en tu historial.',
            );
            navigation.navigate('RampHistory', { initialFilter: 'off_ramp' });
        } catch (err: any) {
            Alert.alert('No se pudo enviar', err?.message || 'Intenta de nuevo en unos minutos.');
        } finally {
            setSendingFromSavings(false);
        }
    };

    const handleSendFunds = () => {
        // Navigate to SendWithAddress with prefilled data
        // @ts-ignore
        navigation.navigate('SendWithAddress', {
            tokenType: 'usdc',
            prefilledAddress: depositAddress,
            prefilledAmount: amount,
        });
    };

    const handleNavigateToWithdraw = () => {
        // @ts-ignore
        navigation.navigate('SendWithAddress', {
            tokenType: 'usdc',
            prefilledAddress: depositAddress,
            prefilledAmount: amount
        });
    };

    if (orderCreated) {
        return (
            <View style={styles.container}>
                <Header
                    navigation={navigation as any}
                    title="Orden Creada"
                    backgroundColor={colors.white}
                    showBackButton
                />

                <ScrollView contentContainerStyle={styles.content}>
                    <View style={styles.successIconContainer}>
                        <Icon name="check" size={40} color={colors.primary} />
                    </View>

                    <Text style={styles.successTitle}>
                        {isSavings ? `Retira desde tu ${balanceNoun}` : 'Envía tus USDC'}
                    </Text>
                    <Text style={styles.successSubtitle}>
                        {isSavings
                            ? `Enviaremos ${amount} US$ directo desde tu ${balanceNoun} a la orden de Guardarian:`
                            : `Enviaremos ${amount} USDC por ti a la orden de Guardarian:`}
                    </Text>

                    <View style={styles.addressCard}>
                        <Text style={styles.addressLabel}>
                            {isSavings ? 'Dirección de depósito (BNB Smart Chain)' : 'Dirección de depósito (Algorand)'}
                        </Text>
                        <TouchableOpacity style={styles.addressContainer} onPress={handleCopyAddress}>
                            <Text style={styles.addressText}>{depositAddress}</Text>
                            <Icon name="copy" size={20} color={colors.accent} />
                        </TouchableOpacity>
                        {depositMemo ? (
                            <View style={styles.memoContainer}>
                                <Text style={styles.memoLabel}>Memo / Tag (Requerido)</Text>
                                <Text style={styles.memoText}>{depositMemo}</Text>
                            </View>
                        ) : null}
                    </View>

                    <View style={styles.warningCard}>
                        <Icon name="alert-triangle" size={20} color={colors.offRampIcon} style={styles.warningIcon} />
                        <Text style={styles.warningText}>
                            {isSavings
                                ? `Completa primero tus datos bancarios en Guardarian; luego toca "Enviar desde mi ${balanceNoun}" y confirmamos el envío por ti.`
                                : 'Completa primero tus datos bancarios en Guardarian; luego toca "Enviar mis fondos" y lo enviamos por ti — sin copiar direcciones.'}
                        </Text>
                    </View>

                    {isSavings ? (
                        <TouchableOpacity
                            style={[styles.ctaButton, sendingFromSavings && styles.ctaButtonDisabled]}
                            onPress={handleSendFromSavings}
                            disabled={sendingFromSavings}
                        >
                            {sendingFromSavings ? (
                                <ActivityIndicator color={colors.white} />
                            ) : (
                                <>
                                    <Text style={styles.ctaButtonText}>{`Enviar desde mi ${balanceNoun}`}</Text>
                                    <Icon name="arrow-right" size={20} color={colors.white} />
                                </>
                            )}
                        </TouchableOpacity>
                    ) : (
                        <TouchableOpacity
                            style={[styles.ctaButton, guardarianSendBusy && styles.ctaButtonDisabled]}
                            onPress={handleAutoSendToGuardarian}
                            disabled={guardarianSendBusy}
                        >
                            {guardarianSendBusy ? (
                                <ActivityIndicator color={colors.white} />
                            ) : (
                                <>
                                    <Text style={styles.ctaButtonText}>Enviar mis fondos</Text>
                                    <Icon name="arrow-right" size={20} color={colors.white} />
                                </>
                            )}
                        </TouchableOpacity>
                    )}
                </ScrollView>
            </View>
        );
    }

    return (
        <View style={styles.container}>
            <Header
                navigation={navigation as any}
                title={isSavings ? `Retirar mi ${balanceNoun}` : 'Vender USDC'}
                backgroundColor={colors.primary}
                isLight
                showBackButton
                rightAccessory={(
                    <TouchableOpacity
                        style={styles.historyButton}
                        onPress={() => navigation.navigate('RampHistory', { initialFilter: 'off_ramp' })}
                        accessibilityRole="button"
                        accessibilityLabel="Ver historial de ventas"
                    >
                        <Text style={styles.historyButtonText}>Historial</Text>
                    </TouchableOpacity>
                )}
            />

            <ScrollView contentContainerStyle={styles.content}>
                {/* Emerald brand field under the flat nav header (PayoutMethods
                    pattern) — padding on fieldInner per the Yoga absolute-child rule. */}
                <View style={styles.brandField}>
                    <Svg style={StyleSheet.absoluteFill}>
                        <Defs>
                            <SvgLinearGradient id="guardarianSellField" x1="0" y1="0" x2="0" y2="1">
                                <Stop offset="0" stopColor={colors.primary} />
                                <Stop offset="1" stopColor={colors.primaryDark} />
                            </SvgLinearGradient>
                        </Defs>
                        <Rect width="100%" height="100%" fill="url(#guardarianSellField)" />
                        <Circle cx="105%" cy="18%" r="80" stroke={colors.white} strokeWidth="20" strokeOpacity="0.10" fill="none" />
                    </Svg>
                    <View style={styles.fieldInner}>
                        <Text style={styles.fieldEyebrow}>
                            {isSavings ? 'RETIRAR CON GUARDARIAN' : 'VENDER CON GUARDARIAN'}
                        </Text>
                        <Text style={styles.fieldTitle}>
                            {isSavings ? 'Retira tu ahorro a tu banco' : 'Vende tus USDC'}
                        </Text>
                        <Text style={styles.fieldSubtitle}>
                            {isSavings
                                ? 'Directo desde tu ahorro a tu cuenta bancaria, sin conversión intermedia.'
                                : 'Convierte tus USDC a moneda local y recíbelos directamente en tu cuenta bancaria.'}
                        </Text>
                    </View>
                </View>

                {/* Info card */}
                <View style={styles.infoCard}>
                    <View style={styles.infoIconContainer}>
                        <Icon name="info" size={16} color="#0EA5E9" />
                    </View>
                    <View style={styles.infoContent}>
                        <Text style={styles.infoCardText}>
                            {userProfile?.email
                                ? `Abriremos Guardarian con tu correo (${userProfile.email.length > 20 ? userProfile.email.substring(0, 20) + '...' : userProfile.email}) pre-configurado.`
                                : `Abriremos Guardarian pre-configurado. Deberás ingresar tu correo electrónico.`
                            }
                        </Text>
                        {!isCountrySupportedForSell && (
                            <Text style={styles.infoCardTextSecondary}>
                                La venta puede no estar disponible en tu país todavía; si Guardarian no ofrece tu moneda, usaremos EUR.
                            </Text>
                        )}
                    </View>
                </View>

                {/* Payout currency selection */}
                {/* Amount Input Card */}
                <View style={styles.inputCard}>
                    <Text style={styles.inputLabel}>
                        {isSavings ? '¿Cuánto quieres retirar?' : '¿Cuánto quieres vender?'}
                    </Text>

                    <View style={styles.amountInputContainer}>
                        <Image source={isSavings ? cUSDPlusLogo : USDCLogo} style={styles.usdcLogo} />
                        <TextInput
                            style={styles.amountInput}
                            placeholder="0"
                            placeholderTextColor={colors.text.light}
                            keyboardType="decimal-pad"
                            value={amount}
                            onChangeText={setAmount}
                        />
                        <View style={styles.currencyBadge}>
                            <Text style={styles.currencyCodeText}>{isSavings ? 'US$' : 'USDC'}</Text>
                        </View>
                    </View>

                    <View style={styles.conversionHint}>
                        <Icon name="arrow-down" size={14} color={colors.offRampIcon} />
                        <Text style={styles.conversionText}>
                            {isSavings
                                ? `Disponible para retirar: $${withdrawableUsd.toFixed(2)}`
                                : 'Recibirás moneda local en tu banco'}
                        </Text>
                    </View>
                </View>

                {/* Features */}
                <View style={styles.featuresContainer}>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="zap" size={16} color={colors.offRampIcon} />
                        </View>
                        <Text style={styles.featureText}>Rápido</Text>
                    </View>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="shield" size={16} color={colors.offRampIcon} />
                        </View>
                        <Text style={styles.featureText}>Seguro</Text>
                    </View>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="credit-card" size={16} color={colors.offRampIcon} />
                        </View>
                        <Text style={styles.featureText}>A tu banco</Text>
                    </View>
                </View>

                {/* CTA Button */}
                <TouchableOpacity
                    style={[styles.ctaButton, (!amount || loading) && styles.ctaButtonDisabled]}
                    onPress={handleCreateOrder}
                    disabled={!amount || loading}
                >
                    {loading ? (
                        <ActivityIndicator color={colors.white} />
                    ) : (
                        <>
                            <Text style={styles.ctaButtonText}>Continuar con Guardarian</Text>
                            <Icon name="arrow-right" size={20} color={colors.white} />
                        </>
                    )}
                </TouchableOpacity>

                <TouchableOpacity
                    style={styles.supportButton}
                    onPress={() => Linking.openURL('https://t.me/confio4world')}
                >
                    <Icon name="help-circle" size={16} color={colors.text.secondary} />
                    <Text style={styles.supportButtonText}>¿Estás perdido? ¡Pide ayuda en soporte!</Text>
                </TouchableOpacity>

                {/* Powered by Guardarian */}
                <View style={styles.poweredByContainer}>
                    <Text style={styles.poweredByLabel}>En alianza con</Text>
                    <View style={styles.guardarianLogoContainer}>
                        <GuardarianLogo width={217} height={24} />
                    </View>
                    <Text style={styles.legalText}>
                        FINFORTIS, S.A. de C.V. es una entidad jurídica constituida de conformidad con las leyes de El Salvador, con código de registro 2024034841 y domicilio legal en Pasaje 8, Oficina 118, Colonia San Benito, San Salvador, El Salvador.
                    </Text>
                </View>

            </ScrollView>

            <PreFlightModal
                visible={showPreFlightModal}
                type="sell"
                ticker={sellTicker}
                onCancel={() => setShowPreFlightModal(false)}
                onContinue={handleProceedToGuardarian}
            />

            {/* Guardarian Return Modal */}
            <GuardarianReturnModal
                visible={showGuardarianReturnModal}
                ticker={sellTicker}
                onContinueSend={async () => {
                    setShowGuardarianReturnModal(false);
                    setAwaitingGuardarianReturn(false);
                    if (isSavings) {
                        if (depositAddress) {
                            await handleSendFromSavings();
                        } else {
                            Alert.alert(
                                'Orden pendiente',
                                'Vuelve a crear el retiro para obtener la dirección de depósito de tu orden.',
                            );
                        }
                        return;
                    }
                    // cUSD rail: server re-derives the deposit address and
                    // sends automatically — no manual SendWithAddress hop.
                    await handleAutoSendToGuardarian();
                }}
                onCancel={async () => {
                    setShowGuardarianReturnModal(false);
                    setAwaitingGuardarianReturn(false);
                }}
            />
        </View>
    );
};

const styles = StyleSheet.create({
  brandField: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
    marginHorizontal: -20,
    marginTop: -20,
    marginBottom: 4,
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 22,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  fieldTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 6,
  },
    container: {
        flex: 1,
        backgroundColor: colors.neutral,
    },
    historyButton: {
        minWidth: 72,
        paddingHorizontal: 12,
        paddingVertical: 8,
        borderRadius: 999,
        backgroundColor: 'rgba(255,255,255,0.18)',
        borderWidth: 1,
        borderColor: 'rgba(255,255,255,0.3)',
        alignItems: 'center',
    },
    historyButtonText: {
        fontSize: 12,
        fontWeight: '700',
        color: colors.white,
    },
    content: {
        padding: 20,
    },
    heroSection: {
        alignItems: 'center',
        marginBottom: 24,
    },
    heroIconContainer: {
        width: 72,
        height: 72,
        borderRadius: 36,
        backgroundColor: colors.warningLight, // Amber-100
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 16,
    },
    heroTitle: {
        fontSize: 28,
        fontWeight: '700',
        color: colors.text.primary,
        marginBottom: 8,
        textAlign: 'center',
    },
    heroSubtitle: {
        fontSize: 15,
        color: colors.text.secondary,
        textAlign: 'center',
        lineHeight: 22,
        paddingHorizontal: 16,
    },

    // Info Card
    infoCard: {
        flexDirection: 'row',
        backgroundColor: '#EFF6FF',
        borderRadius: 12,
        padding: 12,
        marginBottom: 16,
        borderWidth: 1,
        borderColor: '#DBEAFE',
    },
    infoIconContainer: {
        width: 24,
        height: 24,
        borderRadius: 12,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
        marginRight: 10,
        marginTop: 2,
    },
    infoContent: {
        flex: 1,
    },
    infoCardText: {
        fontSize: 12,
        color: colors.text.primary,
        lineHeight: 16,
    },
    infoCardTextSecondary: {
        fontSize: 12,
        color: colors.text.secondary,
        lineHeight: 16,
        marginTop: 4,
    },
    // Amount Input Card
    inputCard: {
        backgroundColor: colors.white,
        borderRadius: 20,
        padding: 20,
        marginBottom: 24,
        shadowColor: '#000',
        shadowOpacity: 0.08,
        shadowRadius: 16,
        shadowOffset: { width: 0, height: 4 },
        elevation: 4,
    },
    inputLabel: {
        fontSize: 15,
        fontWeight: '600',
        color: colors.text.primary,
        marginBottom: 16,
    },
    amountInputContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: colors.neutral,
        borderRadius: 16,
        paddingHorizontal: 16,
        paddingVertical: 16,
        borderWidth: 2,
        borderColor: colors.border,
    },
    currencySymbol: {
        fontSize: 24,
        fontWeight: '700',
        color: colors.text.secondary,
        marginRight: 8,
    },
    usdcLogo: {
        width: 28,
        height: 28,
        marginRight: 8,
        borderRadius: 14,
    },
    amountInput: {
        flex: 1,
        fontSize: 32,
        fontWeight: '700',
        color: colors.text.primary,
        padding: 0,
    },
    currencyBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: colors.white,
        borderRadius: 12,
        paddingHorizontal: 12,
        paddingVertical: 8,
        gap: 6,
    },
    currencyCodeText: {
        fontSize: 14,
        fontWeight: '700',
        color: colors.text.primary,
    },
    conversionHint: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        marginTop: 12,
        gap: 6,
    },
    conversionText: {
        fontSize: 13,
        color: colors.offRampIcon,
        fontWeight: '600',
    },

    // Features
    featuresContainer: {
        flexDirection: 'row',
        justifyContent: 'space-around',
        marginBottom: 32,
    },
    featureItem: {
        alignItems: 'center',
        gap: 8,
    },
    featureIconCircle: {
        width: 48,
        height: 48,
        borderRadius: 24,
        backgroundColor: colors.warningLight, // Amber-100
        alignItems: 'center',
        justifyContent: 'center',
    },
    featureText: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.text.secondary,
    },
    // CTA Button
    ctaButton: {
        backgroundColor: colors.offRampIcon,
        borderRadius: 16,
        paddingVertical: 18,
        paddingHorizontal: 24,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        shadowColor: colors.offRampIcon,
        shadowOpacity: 0.3,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 4,
    },
    ctaButtonDisabled: {
        backgroundColor: colors.borderMedium,
        shadowOpacity: 0,
    },
    ctaButtonText: {
        fontSize: 16,
        fontWeight: '700',
        color: colors.white,
    },
    // Powered by Guardarian
    poweredByContainer: {
        alignItems: 'center',
        marginTop: 24,
        gap: 12,
    },
    poweredByLabel: {
        fontSize: 11,
        color: colors.text.light,
        fontWeight: '500',
        textAlign: 'center',
    },
    guardarianLogoContainer: {
        backgroundColor: colors.white,
        paddingHorizontal: 20,
        paddingVertical: 14,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: colors.border,
        shadowColor: '#000',
        shadowOpacity: 0.04,
        shadowRadius: 8,
        shadowOffset: { width: 0, height: 2 },
        elevation: 2,
        alignItems: 'center',
        justifyContent: 'center',
        minWidth: 260,
    },
    legalText: {
        fontSize: 9,
        color: colors.text.light,
        textAlign: 'center',
        lineHeight: 13,
        paddingHorizontal: 16,
        marginTop: 4,
    },
    successIconContainer: {
        alignSelf: 'center',
        width: 80,
        height: 80,
        borderRadius: 40,
        backgroundColor: colors.primaryLight,
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 24,
    },
    successTitle: {
        fontSize: 24,
        fontWeight: '700',
        color: colors.text.primary,
        textAlign: 'center',
        marginBottom: 8,
    },
    successSubtitle: {
        fontSize: 16,
        color: colors.text.secondary,
        textAlign: 'center',
        marginBottom: 24,
    },
    addressCard: {
        backgroundColor: colors.white,
        borderRadius: 16,
        padding: 20,
        marginBottom: 24,
        borderWidth: 1,
        borderColor: colors.border,
    },
    addressLabel: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.text.secondary,
        marginBottom: 8,
        textTransform: 'uppercase',
    },
    addressContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: colors.neutral,
        padding: 12,
        borderRadius: 8,
    },
    addressText: {
        fontSize: 14,
        color: colors.text.primary,
        flex: 1,
        fontFamily: technicalFontFamily,
    },
    memoContainer: {
        marginTop: 16,
        borderTopWidth: 1,
        borderTopColor: colors.border,
        paddingTop: 16,
    },
    memoLabel: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.text.secondary,
        marginBottom: 4,
    },
    memoText: {
        fontSize: 16,
        fontWeight: '700',
        color: colors.text.primary,
    },
    warningCard: {
        flexDirection: 'row',
        backgroundColor: '#FFFBEB',
        padding: 16,
        borderRadius: 12,
        marginBottom: 24,
        borderWidth: 1,
        borderColor: '#FDE68A',
    },
    warningIcon: {
        marginRight: 12,
    },
    warningText: {
        flex: 1,
        fontSize: 14,
        color: '#92400E',
    },
    supportButton: {
        marginTop: 24,
        marginBottom: 16,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.neutralDark,
        paddingVertical: 10,
        paddingHorizontal: 16,
        borderRadius: 20,
        alignSelf: 'center',
        gap: 8,
    },
    supportButtonText: {
        fontSize: 14,
        color: colors.text.secondary,
        fontWeight: '600',
    },
});
