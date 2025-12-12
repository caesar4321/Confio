import React, { useState, useEffect, useMemo } from 'react';
import {
    View,
    Text,
    StyleSheet,
    SafeAreaView,
    TouchableOpacity,
    TextInput,
    ActivityIndicator,
    Alert,
    ScrollView,
    Platform,
    Clipboard,
    Linking,
    Image,
    StatusBar,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import GuardarianLogo from '../assets/svg/guardarian.svg';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useCountry } from '../contexts/CountryContext';
import { getCurrencyForCountry } from '../utils/currencyMapping';
import { getCountryByIso } from '../utils/countries';
import { createGuardarianTransaction, fetchGuardarianFiatCurrencies, GuardarianFiatCurrency } from '../services/guardarianService';
import { getFlagForCurrency } from '../utils/currencyFlags';
import USDCLogo from '../assets/png/USDC.png';
import PreFlightModal from '../components/PreFlightModal';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'Sell'>;

export const SellScreen = () => {
    const navigation = useNavigation<NavigationProp>();
    const { userProfile } = useAuth() as any;
    const { activeAccount } = useAccount();
    const { selectedCountry, userCountry } = useCountry();

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

    // Order state
    const [orderCreated, setOrderCreated] = useState(false);
    const [depositAddress, setDepositAddress] = useState('');
    const [depositMemo, setDepositMemo] = useState('');
    const [orderId, setOrderId] = useState<number | undefined>(undefined);

    // Whitelist of currencies that Guardarian supports for USDC-ALGO sells
    // Based on testing and Guardarian's API limitations
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
                    setFiatError('Guardarian no soporta retiros en tu moneda. Usaremos EUR como predeterminado.');
                }

            } catch (err: any) {
                console.warn('Guardarian fiat load failed', err);
                setFiatError('No pudimos cargar monedas con retiro. Usaremos EUR.');
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
                fromCurrency: 'USDC',
                // NOTE: Trying without fromNetwork to see if Guardarian auto-detects or uses default
                // fromNetwork: 'ALGO',
                toCurrency: currencyCode,
                email: userProfile?.email,
                customerCountry: userProfile?.phoneCountry,
                externalId: `confio-sell-${Date.now()}`,
            });

            if (tx.deposit_address) {
                setDepositAddress(tx.deposit_address);
                setDepositMemo(tx.deposit_extra_id || '');
                setOrderId(tx.id);
                setOrderCreated(true);
            } else if (tx.redirect_url) {
                try {
                    await Linking.openURL(tx.redirect_url);
                    return;
                } catch (openErr) {
                    console.warn('Failed to open Guardarian redirect', openErr);
                    Alert.alert(
                        'Necesitamos más datos',
                        'Guardarian requiere información adicional. Abre el enlace en tu navegador y completa el proceso.'
                    );
                }
            } else {
                throw new Error('Guardarian no devolvió métodos de retiro. Prueba otra moneda o intenta más tarde.');
            }

        } catch (err: any) {
            console.error('Guardarian sell error', err);
            const msg = String(err?.message || '').toLowerCase();
            if (msg.includes('payout')) {
                setFiatError('Guardarian no ofrece métodos de retiro para esta moneda/país. Prueba otra moneda o cambia de país.');
                setCurrencyCode('');
                Alert.alert(
                    'Sin métodos de retiro',
                    'Guardarian no tiene retiros para esta moneda en tu país. Cambia de moneda y vuelve a intentar.'
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

    const handleSendFunds = () => {
        // Navigate to SendWithAddress with prefilled data
        // @ts-ignore
        navigation.navigate('SendWithAddress', {
            tokenType: 'cusd', // TODO: Update SendWithAddress to support USDC config
            prefilledAddress: depositAddress,
            prefilledAmount: amount,
        });
    };

    const handleNavigateToWithdraw = () => {
        // @ts-ignore
        navigation.navigate('USDCWithdraw', {
            prefilledAddress: depositAddress,
            prefilledAmount: amount
        });
    };

    if (orderCreated) {
        return (
            <SafeAreaView style={styles.container}>
                <View style={styles.header}>
                    <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
                        <Icon name="x" size={24} color="#111827" />
                    </TouchableOpacity>
                    <Text style={styles.headerTitle}>Orden Creada</Text>
                </View>

                <ScrollView contentContainerStyle={styles.content}>
                    <View style={styles.successIconContainer}>
                        <Icon name="check" size={40} color="#34D399" />
                    </View>

                    <Text style={styles.successTitle}>Envía tus USDC</Text>
                    <Text style={styles.successSubtitle}>
                        Para completar la venta, envía exactamente {amount} USDC a la siguiente dirección:
                    </Text>

                    <View style={styles.addressCard}>
                        <Text style={styles.addressLabel}>Dirección de depósito (Algorand)</Text>
                        <TouchableOpacity style={styles.addressContainer} onPress={handleCopyAddress}>
                            <Text style={styles.addressText}>{depositAddress}</Text>
                            <Icon name="copy" size={20} color="#3B82F6" />
                        </TouchableOpacity>
                        {depositMemo ? (
                            <View style={styles.memoContainer}>
                                <Text style={styles.memoLabel}>Memo / Tag (Requerido)</Text>
                                <Text style={styles.memoText}>{depositMemo}</Text>
                            </View>
                        ) : null}
                    </View>

                    <View style={styles.warningCard}>
                        <Icon name="alert-triangle" size={20} color="#F59E0B" style={styles.warningIcon} />
                        <Text style={styles.warningText}>
                            Asegúrate de enviar a través de la red Algorand. Enviar por otra red resultará en pérdida de fondos.
                        </Text>
                    </View>

                    <TouchableOpacity style={styles.ctaButton} onPress={handleNavigateToWithdraw}>
                        <Text style={styles.ctaButtonText}>Ir a Enviar USDC</Text>
                        <Icon name="arrow-right" size={20} color="#fff" />
                    </TouchableOpacity>
                </ScrollView>
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
                    <Icon name="arrow-left" size={24} color="#111827" />
                </TouchableOpacity>
                <Text style={styles.headerTitle}>Retirar USDC a banco</Text>
            </View>

            <ScrollView contentContainerStyle={styles.content}>
                <View style={styles.heroSection}>
                    <View style={styles.heroIconContainer}>
                        <Icon name="dollar-sign" size={32} color="#3B82F6" />
                    </View>
                    <Text style={styles.heroTitle}>Retira a tu banco</Text>
                    <Text style={styles.heroSubtitle}>
                        Convierte tus USDC a moneda local y recíbelos directamente en tu cuenta bancaria. Rápido, seguro y sin complicaciones.
                    </Text>
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
                                Retiros disponibles en EUR {getFlagForCurrency('EUR')} MXN {getFlagForCurrency('MXN')} CLP {getFlagForCurrency('CLP')} COP {getFlagForCurrency('COP')} ARS {getFlagForCurrency('ARS')} BRL {getFlagForCurrency('BRL')}. Tu país actual permite recargar, pero el retiro puede no estar disponible hasta que Guardarian habilite ese mercado.
                            </Text>
                        )}
                    </View>
                </View>

                {/* Payout currency selection */}
                {/* Amount Input Card */}
                <View style={styles.inputCard}>
                    <Text style={styles.inputLabel}>¿Cuánto quieres retirar?</Text>

                    <View style={styles.amountInputContainer}>
                        <Image source={USDCLogo} style={styles.usdcLogo} />
                        <TextInput
                            style={styles.amountInput}
                            placeholder="0"
                            placeholderTextColor="#9CA3AF"
                            keyboardType="decimal-pad"
                            value={amount}
                            onChangeText={setAmount}
                        />
                        <View style={styles.currencyBadge}>
                            <Text style={styles.currencyCodeText}>USDC</Text>
                        </View>
                    </View>

                    <View style={styles.conversionHint}>
                        <Icon name="arrow-down" size={14} color="#3B82F6" />
                        <Text style={styles.conversionText}>Recibirás moneda local en tu banco</Text>
                    </View>
                </View>

                {/* Features */}
                <View style={styles.featuresContainer}>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="zap" size={16} color="#3B82F6" />
                        </View>
                        <Text style={styles.featureText}>Rápido</Text>
                    </View>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="shield" size={16} color="#3B82F6" />
                        </View>
                        <Text style={styles.featureText}>Seguro</Text>
                    </View>
                    <View style={styles.featureItem}>
                        <View style={styles.featureIconCircle}>
                            <Icon name="credit-card" size={16} color="#3B82F6" />
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
                        <ActivityIndicator color="#fff" />
                    ) : (
                        <>
                            <Text style={styles.ctaButtonText}>Continuar con Guardarian</Text>
                            <Icon name="arrow-right" size={20} color="#fff" />
                        </>
                    )}
                </TouchableOpacity>

                <TouchableOpacity
                    style={styles.supportButton}
                    onPress={() => Linking.openURL('https://t.me/confio4world')}
                >
                    <Icon name="help-circle" size={16} color="#4B5563" />
                    <Text style={styles.supportButtonText}>¿Estás perdido? ¡Pide ayuda en soporte!</Text>
                </TouchableOpacity>

                {/* Powered by Guardarian */}
                <View style={styles.poweredByContainer}>
                    <Text style={styles.poweredByLabel}>En alianza con</Text>
                    <View style={styles.guardarianLogoContainer}>
                        <GuardarianLogo width={217} height={24} />
                    </View>
                    <Text style={styles.legalText}>
                        Guardance UAB es una empresa registrada en Lituania (código de registro: 306353686), con dirección en Zalgirio St. 90-100, Vilnius, Lituania. Está registrada bajo el número 306353686 por el Centro Estatal de Registros de la República de Lituania como Operador de Intercambio de Moneda Virtual.
                    </Text>
                </View>

            </ScrollView>

            <PreFlightModal
                visible={showPreFlightModal}
                type="sell"
                onCancel={() => setShowPreFlightModal(false)}
                onContinue={handleProceedToGuardarian}
            />
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#F9FAFB',
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 16,
        paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 0) + 12 : 12,
        paddingBottom: 12,
        backgroundColor: '#fff',
        borderBottomWidth: 1,
        borderBottomColor: '#F3F4F6',
    },
    backButton: {
        padding: 8,
        marginRight: 8,
    },
    headerTitle: {
        fontSize: 18,
        fontWeight: '700',
        color: '#111827',
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
        backgroundColor: '#DBEAFE',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 16,
    },
    heroTitle: {
        fontSize: 28,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 8,
        textAlign: 'center',
    },
    heroSubtitle: {
        fontSize: 15,
        color: '#6B7280',
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
        backgroundColor: '#fff',
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
        color: '#1F2937',
        lineHeight: 16,
    },
    infoCardTextSecondary: {
        fontSize: 12,
        color: '#6B7280',
        lineHeight: 16,
        marginTop: 4,
    },
    // Amount Input Card
    inputCard: {
        backgroundColor: '#fff',
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
        color: '#111827',
        marginBottom: 16,
    },
    amountInputContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#F9FAFB',
        borderRadius: 16,
        paddingHorizontal: 16,
        paddingVertical: 16,
        borderWidth: 2,
        borderColor: '#E5E7EB',
    },
    currencySymbol: {
        fontSize: 24,
        fontWeight: '700',
        color: '#6B7280',
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
        color: '#111827',
        padding: 0,
    },
    currencyBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#fff',
        borderRadius: 12,
        paddingHorizontal: 12,
        paddingVertical: 8,
        gap: 6,
    },
    currencyCodeText: {
        fontSize: 14,
        fontWeight: '700',
        color: '#111827',
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
        color: '#3B82F6',
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
        backgroundColor: '#DBEAFE',
        alignItems: 'center',
        justifyContent: 'center',
    },
    featureText: {
        fontSize: 12,
        fontWeight: '600',
        color: '#6B7280',
    },
    // CTA Button
    ctaButton: {
        backgroundColor: '#3B82F6',
        borderRadius: 16,
        paddingVertical: 18,
        paddingHorizontal: 24,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        shadowColor: '#3B82F6',
        shadowOpacity: 0.3,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 4,
    },
    ctaButtonDisabled: {
        backgroundColor: '#D1D5DB',
        shadowOpacity: 0,
    },
    ctaButtonText: {
        fontSize: 16,
        fontWeight: '700',
        color: '#fff',
    },
    // Powered by Guardarian
    poweredByContainer: {
        alignItems: 'center',
        marginTop: 24,
        gap: 12,
    },
    poweredByLabel: {
        fontSize: 11,
        color: '#9CA3AF',
        fontWeight: '500',
        textAlign: 'center',
    },
    guardarianLogoContainer: {
        backgroundColor: '#fff',
        paddingHorizontal: 20,
        paddingVertical: 14,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#E5E7EB',
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
        color: '#9CA3AF',
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
        backgroundColor: '#D1FAE5',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 24,
    },
    successTitle: {
        fontSize: 24,
        fontWeight: '700',
        color: '#111827',
        textAlign: 'center',
        marginBottom: 8,
    },
    successSubtitle: {
        fontSize: 16,
        color: '#4B5563',
        textAlign: 'center',
        marginBottom: 24,
    },
    addressCard: {
        backgroundColor: '#fff',
        borderRadius: 16,
        padding: 20,
        marginBottom: 24,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    addressLabel: {
        fontSize: 12,
        fontWeight: '600',
        color: '#6B7280',
        marginBottom: 8,
        textTransform: 'uppercase',
    },
    addressContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: '#F9FAFB',
        padding: 12,
        borderRadius: 8,
    },
    addressText: {
        fontSize: 14,
        color: '#111827',
        flex: 1,
        fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    },
    memoContainer: {
        marginTop: 16,
        borderTopWidth: 1,
        borderTopColor: '#E5E7EB',
        paddingTop: 16,
    },
    memoLabel: {
        fontSize: 12,
        fontWeight: '600',
        color: '#6B7280',
        marginBottom: 4,
    },
    memoText: {
        fontSize: 16,
        fontWeight: '700',
        color: '#111827',
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
        backgroundColor: '#F3F4F6',
        paddingVertical: 10,
        paddingHorizontal: 16,
        borderRadius: 20,
        alignSelf: 'center',
        gap: 8,
    },
    supportButtonText: {
        fontSize: 14,
        color: '#4B5563',
        fontWeight: '600',
    },
});
