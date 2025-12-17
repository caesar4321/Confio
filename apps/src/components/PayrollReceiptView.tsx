import React from 'react';
import { View, Text, StyleSheet, Platform, TouchableOpacity, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';

interface PayrollReceiptViewProps {
  employeeName: string;
  employeeUsername: string;
  employeePhone: string;
  businessName: string;
  amount: string;
  currency: string;
  date: string;
  status: string;
  transactionHash: string;
  payrollRunId: string;
  generatedDate?: string;
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

const statusLabel = (status: string) => {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'confirmed':
      return 'Pagado';
    case 'pending':
      return 'Pendiente';
    case 'failed':
      return 'Fallido';
    default:
      return 'Procesado';
  }
};

export const PayrollReceiptView: React.FC<PayrollReceiptViewProps> = ({
  employeeName,
  employeeUsername,
  employeePhone,
  businessName,
  amount,
  currency,
  date,
  status,
  transactionHash,
  payrollRunId,
  generatedDate,
}) => {
  const statusInfo = statusLabel(status);
  const isCompleted = status.toLowerCase() === 'completed' || status.toLowerCase() === 'confirmed';

  return (
    <View style={styles.container}>
      {/* Header - Confío Branding */}
      <View style={styles.brandContainer}>
        <View style={styles.brandBadge}>
          <Icon name="shield" size={32} color="#059669" />
        </View>
        <Text style={styles.brandTitle}>Confío</Text>
        <Text style={styles.brandSubtitle}>Comprobante Oficial de Pago de Nómina</Text>
      </View>

      {/* Status Badge */}
      <View style={[styles.statusBadge, isCompleted ? styles.statusCompleted : styles.statusPending]}>
        <Icon
          name={isCompleted ? 'check-circle' : 'clock'}
          size={16}
          color={isCompleted ? '#059669' : '#d97706'}
        />
        <Text style={[styles.statusText, isCompleted ? styles.statusCompletedText : styles.statusPendingText]}>
          {statusInfo}
        </Text>
      </View>

      {/* Amount Card */}
      <View style={styles.amountCard}>
        <Text style={styles.amountLabel}>Monto pagado</Text>
        <Text style={styles.amountValue}>{amount} {currency}</Text>
        <Text style={styles.amountDate}>{formatDate(date)}</Text>
      </View>

      {/* Employee Details */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Empleado</Text>
        <View style={styles.infoCard}>
          <View style={styles.infoRow}>
            <Icon name="user" size={18} color="#6B7280" />
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Nombre completo</Text>
              <Text style={styles.infoValue}>{employeeName}</Text>
            </View>
          </View>

          {employeeUsername && (
            <View style={styles.infoRow}>
              <Icon name="at-sign" size={18} color="#6B7280" />
              <View style={styles.infoContent}>
                <Text style={styles.infoLabel}>Usuario Confío</Text>
                <Text style={styles.infoValue}>@{employeeUsername}</Text>
              </View>
            </View>
          )}

          {employeePhone && (
            <View style={styles.infoRow}>
              <Icon name="phone" size={18} color="#6B7280" />
              <View style={styles.infoContent}>
                <Text style={styles.infoLabel}>Teléfono</Text>
                <Text style={styles.infoValue}>{employeePhone}</Text>
              </View>
            </View>
          )}
        </View>
      </View>

      {/* Business Details */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Empresa</Text>
        <View style={styles.infoCard}>
          <View style={styles.infoRow}>
            <Icon name="briefcase" size={18} color="#6B7280" />
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Razón social</Text>
              <Text style={styles.infoValue}>{businessName}</Text>
            </View>
          </View>
        </View>
      </View>

      {/* Transaction Details */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Detalles de la transacción</Text>
        <View style={styles.infoCard}>
          {payrollRunId && (
            <View style={styles.infoRow}>
              <Icon name="hash" size={18} color="#6B7280" />
              <View style={styles.infoContent}>
                <Text style={styles.infoLabel}>ID de corrida</Text>
                <Text style={styles.infoValue}>{payrollRunId}</Text>
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

          <View style={styles.infoRow}>
            <Icon name="calendar" size={18} color="#6B7280" />
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Fecha de procesamiento</Text>
              <Text style={styles.infoValue}>{formatDate(date)}</Text>
            </View>
          </View>
        </View>
      </View>

      {/* Verification QR Code */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Verificación</Text>
        <View style={styles.qrCard}>
          <QRCode
            value={`https://confio.lat/verify/${transactionHash}`}
            size={120}
            color="#111827"
            backgroundColor="white"
          />
          <View style={styles.qrTextContainer}>
            <Text style={styles.qrTitle}>Escanear para verificar</Text>
            <Text style={styles.qrDescription}>
              Al abrir el enlace, verifica que aparezca:
            </Text>
            <View style={styles.securityHint}>
              <Text style={styles.securityText}>🔒 Estás en confio.lat</Text>
            </View>
          </View>
        </View>
      </View>

      {/* Certification */}
      <View style={styles.certificationCard}>
        <Icon name="award" size={24} color="#059669" />
        <Text style={styles.certificationTitle}>Certificado por Confío</Text>
        <Text style={styles.certificationText}>
          Este comprobante ha sido generado automáticamente por Confío y certifica que la transacción fue registrada en la blockchain de Algorand.
        </Text>
        <Text style={styles.certificationTimestamp}>
          Generado el {formatDate(generatedDate || new Date().toISOString())}
        </Text>
      </View>

      {/* Footer */}
      <Text style={styles.footer}>
        Este comprobante es válido como prueba de pago de nómina
      </Text>
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
    paddingVertical: 20,
  },
  brandBadge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  brandTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#059669',
    marginBottom: 4,
  },
  brandSubtitle: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
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
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  amountLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 8,
  },
  amountValue: {
    fontSize: 36,
    fontWeight: '700',
    color: '#059669',
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
    fontSize: 16,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 12,
  },
  infoCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    gap: 16,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
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
    fontWeight: '600',
    color: '#111827',
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
  certificationCard: {
    backgroundColor: '#ECFDF5',
    borderRadius: 12,
    padding: 20,
    alignItems: 'center',
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  certificationTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#059669',
    marginTop: 12,
    marginBottom: 8,
  },
  certificationText: {
    fontSize: 13,
    color: '#065F46',
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 12,
  },
  certificationTimestamp: {
    fontSize: 11,
    color: '#6B7280',
    fontStyle: 'italic',
  },
  footer: {
    fontSize: 11,
    color: '#9CA3AF',
    textAlign: 'center',
    lineHeight: 16,
  },
  qrCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 24,
    alignItems: 'center',
    gap: 16,
    flexDirection: 'row',
  },
  qrTextContainer: {
    flex: 1,
    gap: 4,
  },
  qrTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#111827',
  },
  qrDescription: {
    fontSize: 12,
    color: '#6B7280',
    lineHeight: 18,
  },
  securityHint: {
    backgroundColor: '#ECFDF5',
    borderWidth: 1,
    borderColor: '#A7F3D0',
    borderRadius: 8,
    padding: 8,
    marginTop: 4,
  },
  securityText: {
    fontSize: 11,
    color: '#065F46',
    lineHeight: 16,
    fontWeight: '500',
  },
});
