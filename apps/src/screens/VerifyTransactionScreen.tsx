import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, Linking, TouchableOpacity, Alert, Platform } from 'react-native';
import { useRoute, RouteProp, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery, gql } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';

type VerifyScreenRouteProp = RouteProp<MainStackParamList, 'VerifyTransaction'>;
type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'VerifyTransaction'>;

const VERIFY_TRANSACTION = gql`
  query VerifyTransaction($transactionHash: String!) {
    verifyTransaction(transactionHash: $transactionHash) {
        isValid
        status
        transactionHash
        amount
        currency
        timestamp
        senderName
        recipientNameMasked
        recipientPhoneMasked
        verificationMessage
        transactionType
        metadata
    }
  }
`;

export const VerifyTransactionScreen = () => {
    const route = useRoute<VerifyScreenRouteProp>();
    const navigation = useNavigation<NavigationProp>();
    const { hash } = route.params;

    const { loading, error, data, refetch } = useQuery(VERIFY_TRANSACTION, {
        variables: { transactionHash: hash },
        fetchPolicy: 'network-only',
        skip: !hash
    });

    const [metadata, setMetadata] = useState<any>({});

    useEffect(() => {
        if (data?.verifyTransaction?.metadata) {
            try {
                setMetadata(JSON.parse(data.verifyTransaction.metadata));
            } catch (e) {
                console.warn('Failed to parse metadata');
            }
        }
    }, [data]);

    const handleClose = () => {
        if (navigation.canGoBack()) {
            navigation.goBack();
        } else {
            navigation.navigate('BottomTabs', { screen: 'Home' });
        }
    };

    if (loading) {
        return (
            <View style={styles.centerContainer}>
                <ActivityIndicator size="large" color={colors.primary} />
                <Text style={styles.loadingText}>Verificando transacción...</Text>
            </View>
        );
    }

    const result = data?.verifyTransaction;
    const isValid = result?.isValid;
    const isRevoked = result?.status === 'REVOKED';

    // Header title based on status
    const getStatusTitle = () => {
        if (!result) return 'Verificación Fallida';
        if (isValid) return 'Comprobante Validado';
        if (isRevoked) return 'Transacción Revocada';
        return 'Transacción Inválida';
    };

    // Determine labels based on transaction type
    const getLabels = () => {
        const type = result?.transactionType || 'TRANSFER';
        switch (type) {
            case 'PAYROLL':
                return { sender: 'Empresa', recipient: 'Empleado' };
            case 'PAYMENT':
                return { sender: 'Pagador', recipient: 'Comerciante' };
            default:
                return { sender: 'Remitente', recipient: 'Destinatario' };
        }
    };

    const labels = getLabels();

    const StatusIcon = () => {
        if (isValid) return <Icon name="check-circle" size={48} color={colors.success} />;
        if (isRevoked) return <Icon name="alert-triangle" size={48} color="#F59E0B" />;
        return <Icon name="x-circle" size={48} color="#EF4444" />;
    };

    const DetailRow = ({ label, value, isMono = false, subValue }: { label: string, value: string, isMono?: boolean, subValue?: string }) => (
        <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>{label}</Text>
            <Text style={[styles.detailValue, isMono && styles.monoText]}>{value}</Text>
            {subValue ? <Text style={styles.detailSubValue}>{subValue}</Text> : null}
        </View>
    );

    if (!result || error) {
        return (
            <View style={styles.container}>
                <View style={styles.header}>
                    <TouchableOpacity onPress={handleClose} style={styles.closeButton}>
                        <Icon name="x" size={24} color={colors.text} />
                    </TouchableOpacity>
                    <Text style={styles.headerTitle}>Verificación</Text>
                    <View style={{ width: 40 }} />
                </View>

                <View style={[styles.card, styles.errorCard]}>
                    <Icon name="x-circle" size={64} color="#EF4444" style={styles.statusIcon} />
                    <Text style={styles.statusTitle}>No encontrada</Text>
                    <Text style={styles.message}>
                        No pudimos encontrar esta transacción en nuestros registros.
                        El código puede ser incorrecto o la transacción no existe.
                    </Text>
                    <View style={styles.hashBox}>
                        <Text style={styles.hashLabel}>Código consultado:</Text>
                        <Text style={styles.hashText}>{hash}</Text>
                    </View>
                </View>
            </View>
        );
    }

    return (
        <View style={styles.container}>
            <View style={styles.header}>
                <TouchableOpacity onPress={handleClose} style={styles.closeButton}>
                    <Icon name="x" size={24} color={colors.text} />
                </TouchableOpacity>
                <Text style={styles.headerTitle}>Resultado de Verificación</Text>
                <View style={{ width: 40 }} />
            </View>

            <ScrollView contentContainerStyle={styles.scrollContent}>
                <View style={styles.card}>
                    <View style={styles.statusContainer}>
                        <StatusIcon />
                        <Text style={[styles.statusTitle, { color: isValid ? colors.success : (isRevoked ? "#F59E0B" : "#EF4444") }]}>
                            {getStatusTitle()}
                        </Text>
                        <Text style={styles.verificationMessage}>
                            {result.verificationMessage}
                        </Text>
                    </View>

                    {isValid && (
                        <>
                            <View style={styles.divider} />

                            <View style={styles.amountContainer}>
                                <Text style={styles.amountLabel}>Monto</Text>
                                <Text style={styles.amountValue}>
                                    {result.amount} <Text style={styles.currency}>
                                        {result.currency === 'CUSD' ? 'cUSD' : result.currency}
                                    </Text>
                                </Text>
                                <Text style={styles.date}>{new Date(result.timestamp).toLocaleString()}</Text>
                            </View>

                            <View style={styles.section}>
                                <Text style={styles.sectionTitle}>Detalles</Text>
                                <DetailRow label={labels.sender} value={result.senderName} />
                                <DetailRow
                                    label={labels.recipient}
                                    value={result.recipientNameMasked}
                                    subValue={result.recipientPhoneMasked}
                                />
                                {metadata?.referenceId && (
                                    <DetailRow label="Referencia" value={metadata.referenceId} />
                                )}
                                {metadata?.memo && (
                                    <DetailRow label="Concepto" value={metadata.memo} />
                                )}
                            </View>



                            <View style={styles.certificationBox}>
                                <Icon name="shield" size={20} color={colors.primary} />
                                <Text style={styles.certificationText}>
                                    Confío certifica la autenticidad de este comprobante.
                                </Text>
                            </View>
                        </>
                    )}
                </View>
            </ScrollView>
        </View>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: colors.background,
    },
    centerContainer: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: colors.background,
    },
    loadingText: {
        marginTop: 16,
        color: colors.textSecondary,
        fontSize: 16,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: 16,
        paddingTop: Platform.OS === 'android' ? 20 : 60, // Safe area
        paddingBottom: 16,
        backgroundColor: colors.background,
        borderBottomWidth: 1,
        borderBottomColor: colors.neutralDark,
    },
    closeButton: {
        padding: 8,
    },
    headerTitle: {
        fontSize: 18,
        fontWeight: '600',
        color: colors.text,
    },
    scrollContent: {
        padding: 16,
    },
    card: {
        backgroundColor: colors.surface,
        borderRadius: 16,
        padding: 24,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 8,
        elevation: 3,
    },
    errorCard: {
        alignItems: 'center',
        paddingVertical: 40,
        margin: 16,
    },
    statusContainer: {
        alignItems: 'center',
        marginBottom: 24,
    },
    statusIcon: {
        marginBottom: 16,
    },
    statusTitle: {
        fontSize: 22,
        fontWeight: 'bold',
        color: colors.text,
        marginTop: 16,
        marginBottom: 8,
        textAlign: 'center',
    },
    verificationMessage: {
        fontSize: 15,
        color: colors.text,
        textAlign: 'center',
        lineHeight: 22,
    },
    message: {
        fontSize: 15,
        color: colors.text,
        textAlign: 'center',
        marginBottom: 24,
    },
    divider: {
        height: 1,
        backgroundColor: colors.neutralDark,
        marginVertical: 20,
    },
    amountContainer: {
        alignItems: 'center',
        marginBottom: 24,
    },
    amountLabel: {
        fontSize: 13,
        color: colors.textSecondary,
        marginBottom: 4,
    },
    amountValue: {
        fontSize: 32,
        fontWeight: 'bold',
        color: colors.text,
    },
    currency: {
        fontSize: 20,
        fontWeight: '600',
        color: colors.textSecondary,
    },
    date: {
        fontSize: 13,
        color: colors.textSecondary,
        marginTop: 8,
    },
    section: {
        marginBottom: 24,
    },
    sectionTitle: {
        fontSize: 15,
        fontWeight: '600',
        color: colors.text,
        marginBottom: 12,
    },
    detailRow: {
        marginBottom: 16,
    },
    detailLabel: {
        fontSize: 12,
        color: colors.textSecondary,
        marginBottom: 4,
    },
    detailValue: {
        fontSize: 16,
        color: colors.text,
        fontWeight: '500',
    },
    detailSubValue: {
        fontSize: 13,
        color: colors.textSecondary,
        marginTop: 2,
    },
    monoText: {
        fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
        fontSize: 13,
    },
    hashBox: {
        backgroundColor: colors.neutralDark,
        padding: 12,
        borderRadius: 8,
        width: '100%',
    },
    hashLabel: {
        fontSize: 12,
        color: colors.textSecondary,
        marginBottom: 4,
    },
    hashText: {
        fontSize: 13,
        fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
        color: colors.text,
    },
    hashRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: colors.neutralDark,
        padding: 12,
        borderRadius: 8,
    },
    certificationBox: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#ECFDF5',
        padding: 12,
        borderRadius: 8,
        gap: 12,
        marginTop: 8,
    },
    certificationText: {
        fontSize: 12,
        color: '#065F46',
        flex: 1,
        lineHeight: 18,
    }
});
