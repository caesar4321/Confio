import React from 'react';
import { View, Text, StyleSheet, Platform } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

interface PayrollRunReceiptViewProps {
  businessName: string;
  runId: string;
  status: string;
  scheduledDate: string;
  totalAmount: string;
  currency: string;
  employeeCount: number;
  completedCount: number;
  employees: Array<{
    name: string;
    username: string;
    amount: string;
    status: string;
  }>;
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
      return 'Completada';
    case 'pending':
      return 'Pendiente';
    case 'failed':
      return 'Fallida';
    default:
      return 'Procesada';
  }
};

const employeeStatusLabel = (status: string) => {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'confirmed':
      return { label: 'Pagado', color: '#059669', bg: '#D1FAE5', icon: 'check-circle' };
    case 'pending':
      return { label: 'Pendiente', color: '#d97706', bg: '#FEF3C7', icon: 'clock' };
    case 'failed':
      return { label: 'Fallido', color: '#dc2626', bg: '#FEE2E2', icon: 'x-circle' };
    default:
      return { label: 'Procesado', color: '#6B7280', bg: '#F3F4F6', icon: 'help-circle' };
  }
};

export const PayrollRunReceiptView: React.FC<PayrollRunReceiptViewProps> = ({
  businessName,
  runId,
  status,
  scheduledDate,
  totalAmount,
  currency,
  employeeCount,
  completedCount,
  employees,
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
        <Text style={styles.brandSubtitle}>Comprobante de Corrida de Nómina</Text>
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
          <View style={styles.infoRow}>
            <Icon name="hash" size={18} color="#6B7280" />
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Corrida de nómina</Text>
              <Text style={styles.infoValue}>#{runId}</Text>
            </View>
          </View>
          <View style={styles.infoRow}>
            <Icon name="calendar" size={18} color="#6B7280" />
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Fecha programada</Text>
              <Text style={styles.infoValue}>{formatDate(scheduledDate)}</Text>
            </View>
          </View>
        </View>
      </View>

      {/* Summary Card */}
      <View style={styles.summaryCard}>
        <Text style={styles.summaryLabel}>Total pagado</Text>
        <Text style={styles.summaryValue}>{totalAmount} {currency}</Text>
        <View style={styles.summaryStats}>
          <View style={styles.statItem}>
            <Icon name="users" size={16} color="#059669" />
            <Text style={styles.statText}>{employeeCount} empleados</Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Icon name="check-circle" size={16} color="#059669" />
            <Text style={styles.statText}>{completedCount} completados</Text>
          </View>
        </View>
      </View>

      {/* Employee List */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Detalle de pagos ({employees.length})</Text>
        <View style={styles.employeeList}>
          {employees.map((emp, idx) => {
            const empStatus = employeeStatusLabel(emp.status);
            return (
              <View key={idx} style={styles.employeeRow}>
                <View style={[styles.employeeStatusIcon, { backgroundColor: empStatus.bg }]}>
                  <Icon name={empStatus.icon as any} size={14} color={empStatus.color} />
                </View>
                <View style={styles.employeeInfo}>
                  <Text style={styles.employeeName}>{emp.name}</Text>
                  {emp.username && (
                    <Text style={styles.employeeUsername}>@{emp.username}</Text>
                  )}
                </View>
                <View style={styles.employeeAmount}>
                  <Text style={styles.employeeAmountValue}>{emp.amount}</Text>
                  <Text style={styles.employeeAmountCurrency}>{currency}</Text>
                </View>
              </View>
            );
          })}
        </View>
      </View>

      {/* Certification */}
      <View style={styles.certificationCard}>
        <Icon name="award" size={24} color="#059669" />
        <Text style={styles.certificationTitle}>Certificado por Confío</Text>
        <Text style={styles.certificationText}>
          Este comprobante ha sido generado automáticamente por Confío y certifica que la corrida de nómina fue autorizada y procesada en la blockchain de Algorand.
        </Text>
        <Text style={styles.certificationTimestamp}>
          Generado el {formatDate(generatedDate || new Date().toISOString())}
        </Text>
      </View>

      {/* Footer */}
      <Text style={styles.footer}>
        Este comprobante es válido como prueba de corrida de nómina
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
  summaryCard: {
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
  summaryLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 8,
  },
  summaryValue: {
    fontSize: 36,
    fontWeight: '700',
    color: '#059669',
    marginBottom: 16,
  },
  summaryStats: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  statItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statDivider: {
    width: 1,
    height: 16,
    backgroundColor: '#E5E7EB',
  },
  statText: {
    fontSize: 13,
    color: '#6B7280',
    fontWeight: '500',
  },
  employeeList: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    gap: 12,
  },
  employeeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  employeeStatusIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  employeeInfo: {
    flex: 1,
  },
  employeeName: {
    fontSize: 14,
    fontWeight: '600',
    color: '#111827',
  },
  employeeUsername: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 2,
  },
  employeeAmount: {
    alignItems: 'flex-end',
  },
  employeeAmountValue: {
    fontSize: 15,
    fontWeight: '700',
    color: '#059669',
  },
  employeeAmountCurrency: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 2,
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
});
