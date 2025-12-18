import React from 'react';
import { View, Text, StyleSheet, Platform, TouchableOpacity, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';

export interface TransactionReceiptViewProps {
    type: 'payroll' | 'payment' | 'transfer';
    senderName: string;
    senderLabel: string; // 'Empresa', 'Pagador', 'Remitente'
    senderDetail?: string; // Phone/Username
    recipientName: string;
    recipientLabel: string; // 'Empleado', 'Comerciante', 'Destinatario'
    recipientDetail?: string; // Phone/Username
    amount: string;
    currency: string;
    date: string;
    status: string;
    transactionHash: string;
    referenceId?: string; // Run ID, Invoice ID, etc.
    referenceLabel?: string; // 'ID de corrida', 'Factura', etc.
    memo?: string;
    generatedDate?: string;
    verificationId?: string; // Internal ID for QR code (explicitly separate from display hash)
}

const formatDate = (iso?: string | null) => {
    if (!iso) return 'Sin fecha';
    const d = new Date(iso);
    return d.toLocaleDateString('es', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
};

const statusLabel = (status: string, type: string) => {
    const s = status.toLowerCase();
    // Confirmed-like statuses show "Confirmado" (confirmed, completed, paid)
    if (s === 'confirmed' || s === 'completed' || s === 'paid') return 'Confirmado';
    if (s === 'failed') return 'Fallido';
    // Pending statuses show "Confirmando…"
    return 'Confirmando…';
};

const getHeaderTitle = (type: string) => {
    switch (type) {
        case 'payroll': return 'Comprobante de Nómina';
        case 'payment': return 'Comprobante de Pago';
        case 'transfer': return 'Comprobante de Transferencia';
        default: return 'Comprobante de Transacción';
    }
};

export const TransactionReceiptView: React.FC<TransactionReceiptViewProps> = ({
    type,
    senderName,
    senderLabel,
    senderDetail,
    recipientName,
    recipientLabel,
    recipientDetail,
    amount,
    currency,
    date,
    status,
    transactionHash,
    referenceId,
    referenceLabel,
    memo,
    generatedDate,
    verificationId,
}) => {
    const s = status.toLowerCase();
    // Confirmed-like statuses get green styling (confirmed, completed, paid)
    const isCompleted = s === 'confirmed' || s === 'completed' || s === 'paid';
    const statusText = statusLabel(status, type);

    return (
        <View style={styles.container}>
            {/* Header - Confío Branding */}
            <View style={styles.brandContainer}>
                <View style={styles.brandBadge}>
                    <Icon name="shield" size={32} color="#059669" />
                </View>
                <Text style={styles.brandTitle}>Confío</Text>
                <Text style={styles.brandSubtitle}>Comprobante Oficial</Text>
                <Text style={styles.typeSubtitle}>{getHeaderTitle(type)}</Text>
            </View>

            {/* Status Badge */}
            <View style={[styles.statusBadge, isCompleted ? styles.statusCompleted : styles.statusPending]}>
                <Icon
                    name={isCompleted ? 'check-circle' : 'clock'}
                    size={16}
                    color={isCompleted ? '#059669' : '#d97706'}
                />
                <Text style={[styles.statusText, isCompleted ? styles.statusCompletedText : styles.statusPendingText]}>
                    {statusText}
                </Text>
            </View>

            {/* Amount Card */}
            <View style={styles.amountCard}>
                <Text style={styles.amountLabel}>Monto</Text>
                <Text style={styles.amountValue}>{amount} {currency}</Text>
                <Text style={styles.amountDate}>{formatDate(date)}</Text>
            </View>

            {/* Participants Card */}
            <View style={styles.section}>
                <Text style={styles.sectionTitle}>Detalles</Text>
                <View style={styles.infoCard}>
                    {/* Sender */}
                    <View style={styles.infoRow}>
                        <Icon name="arrow-up-right" size={18} color="#6B7280" />
                        <View style={styles.infoContent}>
                            <Text style={styles.infoLabel}>{senderLabel}</Text>
                            <Text style={styles.infoValue}>{senderName}</Text>
                            {senderDetail && <Text style={styles.infoSubValue}>{senderDetail}</Text>}
                        </View>
                    </View>

                    <View style={styles.divider} />

                    {/* Recipient */}
                    <View style={styles.infoRow}>
                        <Icon name="arrow-down-left" size={18} color="#6B7280" />
                        <View style={styles.infoContent}>
                            <Text style={styles.infoLabel}>{recipientLabel}</Text>
                            <Text style={styles.infoValue}>{recipientName}</Text>
                            {recipientDetail && <Text style={styles.infoSubValue}>{recipientDetail}</Text>}
                        </View>
                    </View>
                </View>
            </View>

            {/* Transaction Metadata */}
            <View style={styles.section}>
                <Text style={styles.sectionTitle}>Datos adicionales</Text>
                <View style={styles.infoCard}>
                    {referenceId && (
                        <View style={styles.infoRow}>
                            <Icon name="hash" size={18} color="#6B7280" />
                            <View style={styles.infoContent}>
                                <Text style={styles.infoLabel}>{referenceLabel || 'Referencia'}</Text>
                                <Text style={styles.infoValue}>{referenceId}</Text>
                            </View>
                        </View>
                    )}

                    {memo && (
                        <View style={styles.infoRow}>
                            <Icon name="message-square" size={18} color="#6B7280" />
                            <View style={styles.infoContent}>
                                <Text style={styles.infoLabel}>Concepto</Text>
                                <Text style={styles.infoValue}>{memo}</Text>
                            </View>
                        </View>
                    )}

                    {transactionHash && (
                        <TouchableOpacity
                            style={styles.infoRow}
                            onPress={() => {
                                const base = __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
                                const url = `${base}/tx/${transactionHash}`;
                                Linking.openURL(url);
                            }}
                            activeOpacity={0.7}
                        >
                            <Icon name="link" size={18} color="#059669" />
                            <View style={styles.infoContent}>
                                <Text style={styles.infoLabel}>Hash blockchain</Text>
                                <View style={styles.hashContainer}>
                                    <Text style={styles.infoValueMono} numberOfLines={1}>{transactionHash}</Text>
                                    <Icon name="external-link" size={14} color="#059669" style={styles.externalIcon} />
                                </View>
                            </View>
                        </TouchableOpacity>
                    )}
                </View>
            </View>

            {/* Verification QR Code - only show if we have a valid verification ID (not transaction hash) */}
            {verificationId && (
                <View style={styles.section}>
                    <Text style={styles.sectionTitle}>Verificación</Text>
                    <View style={styles.qrCard}>
                        <QRCode
                            value={`https://confio.lat/verify/${verificationId}`}
                            size={80}
                        />
                        <View style={styles.qrTextContainer}>
                            <Text style={styles.qrTitle}>Escanear para verificar</Text>
                            <Text style={styles.qrDescription}>
                                Comprueba la autenticidad de este recibo en confio.lat
                            </Text>
                        </View>
                    </View>
                </View>
            )}

            {/* Certification Footer */}
            <View style={styles.certificationCard}>
                <Icon name="award" size={20} color="#059669" />
                <Text style={styles.certificationTitle}>Certificado por Confío</Text>
                <Text style={styles.certificationText}>
                    Confío certifica la coincidencia de los datos del comprobante con la transacción registrada en Algorand.
                </Text>
                <Text style={styles.certificationTimestamp}>
                    Generado el {formatDate(generatedDate || new Date().toISOString())}
                </Text>
            </View>
        </View>
    );
};

const styles = StyleSheet.create({
    container: {
        backgroundColor: '#F9FAFB',
        padding: 20,
    },
    brandContainer: {
        alignItems: 'center',
        marginBottom: 24,
        paddingVertical: 10,
    },
    brandBadge: {
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: '#D1FAE5',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 12,
    },
    brandTitle: {
        fontSize: 22,
        fontWeight: '700',
        color: '#059669',
        marginBottom: 2,
    },
    brandSubtitle: {
        fontSize: 13,
        color: '#6B7280',
        textAlign: 'center',
    },
    typeSubtitle: {
        fontSize: 15,
        fontWeight: '600',
        color: '#111827',
        marginTop: 4,
    },
    statusBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        alignSelf: 'center',
        paddingHorizontal: 16,
        paddingVertical: 8,
        borderRadius: 20,
        gap: 6,
        marginBottom: 24,
    },
    statusCompleted: {
        backgroundColor: '#D1FAE5',
    },
    statusPending: {
        backgroundColor: '#FEF3C7',
    },
    statusText: {
        fontSize: 14,
        fontWeight: '600',
    },
    statusCompletedText: {
        color: '#059669',
    },
    statusPendingText: {
        color: '#d97706',
    },
    amountCard: {
        backgroundColor: '#fff',
        borderRadius: 16,
        padding: 24,
        alignItems: 'center',
        marginBottom: 24,
        shadowColor: '#000',
        shadowOpacity: 0.05,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 2,
    },
    amountLabel: {
        fontSize: 13,
        color: '#6B7280',
        marginBottom: 8,
    },
    amountValue: {
        fontSize: 32,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 8,
    },
    amountDate: {
        fontSize: 13,
        color: '#9CA3AF',
    },
    section: {
        marginBottom: 20,
    },
    sectionTitle: {
        fontSize: 15,
        fontWeight: '600',
        color: '#374151',
        marginBottom: 12,
        marginLeft: 4,
    },
    infoCard: {
        backgroundColor: '#fff',
        borderRadius: 12,
        padding: 16,
        gap: 16,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    infoRow: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
        paddingVertical: 4,
    },
    divider: {
        height: 1,
        backgroundColor: '#E5E7EB',
        marginVertical: 4,
    },
    infoContent: {
        flex: 1,
    },
    infoLabel: {
        fontSize: 12,
        color: '#6B7280',
        marginBottom: 4,
    },
    infoValue: {
        fontSize: 15,
        fontWeight: '500',
        color: '#111827',
    },
    infoSubValue: {
        fontSize: 13,
        color: '#6B7280',
        marginTop: 2,
    },
    infoValueMono: {
        fontSize: 13,
        fontWeight: '500',
        color: '#059669',
        fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
        flex: 1,
    },
    hashContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    externalIcon: {
        marginLeft: 4,
    },
    qrCard: {
        backgroundColor: '#fff',
        borderRadius: 12,
        padding: 20,
        alignItems: 'center',
        gap: 16,
        flexDirection: 'row',
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    qrTextContainer: {
        flex: 1,
        gap: 4,
    },
    qrTitle: {
        fontSize: 15,
        fontWeight: '600',
        color: '#111827',
    },
    qrDescription: {
        fontSize: 12,
        color: '#6B7280',
        lineHeight: 18,
    },
    certificationCard: {
        backgroundColor: '#ECFDF5',
        borderRadius: 12,
        padding: 16,
        alignItems: 'center',
        marginBottom: 40,
        borderWidth: 1,
        borderColor: '#A7F3D0',
    },
    certificationTitle: {
        fontSize: 14,
        fontWeight: '700',
        color: '#059669',
        marginTop: 8,
        marginBottom: 6,
    },
    certificationText: {
        fontSize: 12,
        color: '#064E3B',
        textAlign: 'center',
        lineHeight: 18,
        marginBottom: 8,
    },
    certificationTimestamp: {
        fontSize: 11,
        color: '#6B7280',
        fontStyle: 'italic',
    },
});
