import React, { useMemo, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  SafeAreaView,
  ScrollView,
  Alert,
  Platform,
} from 'react-native';
import Share from 'react-native-share';
import Icon from 'react-native-vector-icons/Feather';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import ViewShot from 'react-native-view-shot';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import { MainStackParamList } from '../types/navigation';
import { PayrollReceiptView } from '../components/PayrollReceiptView';
import { PayrollRunReceiptView } from '../components/PayrollRunReceiptView';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollRunDetail'>;
type RouteProps = RouteProp<MainStackParamList, 'PayrollRunDetail'>;

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

const formatShortDate = (iso?: string | null) => {
  if (!iso) return 'Sin fecha';
  const d = new Date(iso);
  return d.toLocaleDateString('es', { year: 'numeric', month: 'short', day: 'numeric' });
};

const formatCurrency = (amount: number) => {
  return new Intl.NumberFormat('es', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
};

const statusLabel = (status: string) => {
  const key = (status || '').toLowerCase();
  switch (key) {
    case 'completed':
    case 'confirmed':
      return { label: 'Completada', color: '#059669', bg: '#D1FAE5', icon: 'check-circle' };
    case 'prepared':
    case 'ready':
      return { label: 'Lista', color: '#4F46E5', bg: '#E0E7FF', icon: 'clock' };
    case 'submitted':
      return { label: 'Procesando', color: '#2563EB', bg: '#DBEAFE', icon: 'loader' };
    case 'pending':
      return { label: 'Pendiente', color: '#D97706', bg: '#FEF3C7', icon: 'alert-circle' };
    case 'failed':
    case 'cancelled':
      return { label: 'Fallida', color: '#DC2626', bg: '#FEE2E2', icon: 'x-circle' };
    default:
      return { label: status || '—', color: '#6B7280', bg: '#F3F4F6', icon: 'help-circle' };
  }
};

export const PayrollRunDetailScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const route = useRoute<RouteProps>();
  const run = route.params?.run as any;
  const [capturingIndex, setCapturingIndex] = useState<number | null>(null);
  const [capturingFullRun, setCapturingFullRun] = useState(false);
  const receiptRefs = useRef<{ [key: number]: ViewShot | null }>({});
  const fullRunRef = useRef<ViewShot>(null);

  const items = useMemo(() => run?.items || [], [run?.items]);
  const total = useMemo(
    () => items.reduce((acc: number, it: any) => acc + (Number(it.netAmount) || 0), 0),
    [items]
  );
  const businessName = run?.business?.name || 'Negocio';
  const status = statusLabel(run?.status);

  const stats = useMemo(() => {
    const completed = items.filter((it: any) =>
      (it.status || '').toLowerCase() === 'completed' ||
      (it.status || '').toLowerCase() === 'confirmed'
    ).length;

    return {
      total: items.length,
      completed,
      pending: items.length - completed,
    };
  }, [items]);

  const handleSharePdf = async () => {
    try {
      // Trigger rendering of the full run receipt
      setCapturingFullRun(true);

      // Wait for the next render cycle
      await new Promise(resolve => setTimeout(resolve, 100));

      if (!fullRunRef.current) {
        Alert.alert('Error', 'El comprobante no está listo para exportar.', [{ text: 'OK' }]);
        setCapturingFullRun(false);
        return;
      }

      // Utilities
      const uri = await fullRunRef.current?.capture?.();
      if (!uri) {
        throw new Error('No se pudo generar la imagen del comprobante.');
      }

      // Save directly to Camera Roll (complies with Google Play policy)
      const savedUri = await CameraRoll.save(uri, { type: 'photo' });

      Alert.alert(
        'Comprobante guardado',
        'El comprobante se guardó en tu galería de fotos.',
        [
          { text: 'OK', onPress: () => setCapturingFullRun(false) },
          {
            text: 'Compartir',
            onPress: async () => {
              try {
                const message = `Corrida #${run?.runId || run?.id?.slice(0, 6)} - ${businessName}`;

                await Share.open({
                  title: 'Comprobante de Corrida de Nómina',
                  message,
                  url: uri,
                  type: 'image/jpeg',
                });
              } catch (error) {
                console.error('Share error:', error);
              }
              setCapturingFullRun(false);
            },
          },
        ]
      );
    } catch (e: any) {
      console.error('PDF share error', e);
      Alert.alert('Error', 'No se pudo guardar el comprobante. Verifica los permisos de galería.', [{ text: 'OK' }]);
      setCapturingFullRun(false);
    }
  };

  const handleShareItemPdf = async (it: any, idx: number) => {
    try {
      const acctUser = it.recipientAccount?.user;
      const name = `${it.recipientUser?.firstName || acctUser?.firstName || ''} ${it.recipientUser?.lastName || acctUser?.lastName || ''}`.trim()
        || it.recipientUser?.username || acctUser?.username || 'Empleado';

      // Trigger rendering of the receipt
      setCapturingIndex(idx);

      // Wait for the next render cycle
      await new Promise(resolve => setTimeout(resolve, 100));

      const ref = receiptRefs.current[idx];
      if (!ref) {
        Alert.alert('Error', 'El comprobante no está listo para exportar.', [{ text: 'OK' }]);
        setCapturingIndex(null);
        return;
      }

      // Capture the view as an image
      const uri = await ref?.capture?.();
      if (!uri) {
        throw new Error('No se pudo generar la imagen del comprobante.');
      }

      // Save directly to Camera Roll (complies with Google Play policy)
      const savedUri = await CameraRoll.save(uri, { type: 'photo' });

      Alert.alert(
        'Comprobante guardado',
        'El comprobante se guardó en tu galería de fotos.',
        [
          { text: 'OK', onPress: () => setCapturingIndex(null) },
          {
            text: 'Compartir',
            onPress: async () => {
              try {
                const message = `Pago de nómina - ${name}`;

                await Share.open({
                  title: 'Comprobante de Pago de Nómina',
                  message,
                  url: uri,
                  type: 'image/jpeg',
                });
              } catch (error) {
                console.error('Share error:', error);
              }
              setCapturingIndex(null);
            },
          },
        ]
      );
    } catch (e: any) {
      console.error('Item PDF share error', e);
      Alert.alert('Error', 'No se pudo guardar el comprobante. Verifica los permisos de galería.');
      setCapturingIndex(null);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.content}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={22} color="#111827" />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Corrida #{run?.runId || run?.id?.slice(0, 6)}</Text>
            <Text style={styles.subtitle}>{businessName}</Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: status.bg }]}>
            <Icon name={status.icon as any} size={14} color={status.color} />
            <Text style={[styles.statusText, { color: status.color }]}>{status.label}</Text>
          </View>
        </View>

        {/* Summary Card */}
        <View style={styles.summaryCard}>
          <View style={styles.summaryHeader}>
            <Icon name="info" size={20} color="#059669" />
            <Text style={styles.summaryTitle}>Resumen de la corrida</Text>
          </View>

          <View style={styles.summaryGrid}>
            <View style={styles.summaryItem}>
              <Icon name="calendar" size={16} color="#6B7280" />
              <Text style={styles.summaryLabel}>Fecha programada</Text>
              <Text style={styles.summaryValue}>{formatShortDate(run?.scheduledAt || run?.createdAt)}</Text>
            </View>

            <View style={styles.summaryDivider} />

            <View style={styles.summaryItem}>
              <Icon name="users" size={16} color="#6B7280" />
              <Text style={styles.summaryLabel}>Empleados</Text>
              <Text style={styles.summaryValue}>{items.length}</Text>
            </View>
          </View>

          <View style={styles.totalAmountCard}>
            <Text style={styles.totalAmountLabel}>Total neto</Text>
            <Text style={styles.totalAmountValue}>{formatCurrency(total)} cUSD</Text>
            {stats.pending > 0 && (
              <Text style={styles.totalAmountSubtext}>
                {stats.completed} de {stats.total} pagos completados
              </Text>
            )}
          </View>
        </View>

        {/* Employee List Section */}
        <View style={styles.sectionHeader}>
          <View style={styles.sectionTitleRow}>
            <Icon name="briefcase" size={18} color="#111827" />
            <Text style={styles.sectionTitle}>Pagos individuales ({items.length})</Text>
          </View>
          <Text style={styles.sectionSubtitle}>Toca "Recibo" para descargar el comprobante individual</Text>
        </View>

        {items.map((it: any, idx: number) => {
          const acctUser = it.recipientAccount?.user;
          console.log(`[PayrollRunDetail] Item ${idx}:`, {
            recipientUser: it.recipientUser,
            recipientAccountUser: acctUser,
            firstName: it.recipientUser?.firstName,
            lastName: it.recipientUser?.lastName,
            username: it.recipientUser?.username
          });
          const name = `${it.recipientUser?.firstName || acctUser?.firstName || ''} ${it.recipientUser?.lastName || acctUser?.lastName || ''}`.trim()
            || it.recipientUser?.username || acctUser?.username || 'Empleado';
          const itemStatus = statusLabel(it.status);

          return (
            <View key={it.id || idx} style={styles.employeeCard}>
              <View style={styles.employeeHeader}>
                <View style={[styles.employeeIconBadge, { backgroundColor: itemStatus.bg }]}>
                  <Icon name={itemStatus.icon as any} size={18} color={itemStatus.color} />
                </View>
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <Text style={styles.employeeName}>{name}</Text>
                  {it.recipientUser?.username && (
                    <Text style={styles.employeeUsername}>@{it.recipientUser.username}</Text>
                  )}
                </View>
                <View style={[styles.employeeStatusBadge, { backgroundColor: itemStatus.bg }]}>
                  <Text style={[styles.employeeStatusText, { color: itemStatus.color }]}>
                    {itemStatus.label}
                  </Text>
                </View>
              </View>

              <View style={styles.employeeDivider} />

              <View style={styles.employeeDetails}>
                <View style={styles.employeeDetailRow}>
                  <Icon name="dollar-sign" size={16} color="#6B7280" />
                  <Text style={styles.employeeDetailLabel}>Monto</Text>
                  <Text style={styles.employeeDetailValue}>{formatCurrency(Number(it.netAmount || 0))} cUSD</Text>
                </View>

                {it.recipientAccount && (
                  <View style={styles.employeeDetailRow}>
                    <Icon name="credit-card" size={16} color="#6B7280" />
                    <Text style={styles.employeeDetailLabel}>Cuenta</Text>
                    <Text style={styles.employeeDetailValue} numberOfLines={1}>
                      {it.recipientAccount?.id?.slice(0, 12) || it.recipientAccount?.accountId?.slice(0, 12) || 'N/A'}...
                    </Text>
                  </View>
                )}
              </View>

              <TouchableOpacity
                style={styles.receiptButton}
                onPress={() => handleShareItemPdf(it, idx)}
                activeOpacity={0.7}
              >
                <Icon name="download" size={16} color="#059669" />
                <Text style={styles.receiptButtonText}>Descargar recibo individual</Text>
              </TouchableOpacity>
            </View>
          );
        })}

        {/* Action Buttons */}
        <View style={styles.actionsContainer}>
          <TouchableOpacity style={styles.primaryButton} onPress={handleSharePdf}>
            <Icon name="file-text" size={20} color="#fff" />
            <Text style={styles.primaryButtonText}>Descargar comprobante completo</Text>
          </TouchableOpacity>

          <Text style={styles.actionsHint}>
            El comprobante incluye todos los pagos de esta corrida
          </Text>
        </View>

        {/* Hidden receipt views for capture - only render the one being captured */}
        {capturingIndex !== null && items[capturingIndex] && (() => {
          const it = items[capturingIndex];
          const acctUser = it.recipientAccount?.user;
          const name = `${it.recipientUser?.firstName || acctUser?.firstName || ''} ${it.recipientUser?.lastName || acctUser?.lastName || ''}`.trim()
            || it.recipientUser?.username || acctUser?.username || 'Empleado';
          const username = it.recipientUser?.username || acctUser?.username || '';
          const phone = it.recipientUser?.phoneKey || acctUser?.phoneKey || '';

          return (
            <View style={styles.hiddenReceipt}>
              <ViewShot
                ref={(ref) => { receiptRefs.current[capturingIndex] = ref; }}
                options={{ format: 'jpg', quality: 0.9 }}
              >
                <PayrollReceiptView
                  employeeName={name}
                  employeeUsername={username}
                  employeePhone={phone}
                  businessName={businessName}
                  amount={formatCurrency(Number(it.netAmount || 0))}
                  currency="cUSD"
                  date={run?.scheduledAt || run?.createdAt || new Date().toISOString()}
                  status={it.status || 'completed'}
                  transactionHash={it.transactionHash || ''}
                  payrollRunId={run?.runId || run?.id?.slice(0, 6) || ''}
                  generatedDate={new Date().toISOString()}
                />
              </ViewShot>
            </View>
          );
        })()}

        {/* Hidden full run receipt for capture */}
        {capturingFullRun && (
          <View style={styles.hiddenReceipt}>
            <ViewShot ref={fullRunRef} options={{ format: 'jpg', quality: 0.9 }}>
              <PayrollRunReceiptView
                businessName={businessName}
                runId={run?.runId || run?.id?.slice(0, 6) || ''}
                status={run?.status || 'completed'}
                scheduledDate={run?.scheduledAt || run?.createdAt || new Date().toISOString()}
                totalAmount={formatCurrency(total)}
                currency="cUSD"
                employeeCount={items.length}
                completedCount={stats.completed}
                employees={items.map((it: any) => {
                  const acctUser = it.recipientAccount?.user;
                  const name = `${it.recipientUser?.firstName || acctUser?.firstName || ''} ${it.recipientUser?.lastName || acctUser?.lastName || ''}`.trim()
                    || it.recipientUser?.username || acctUser?.username || 'Empleado';
                  const username = it.recipientUser?.username || acctUser?.username || '';
                  return {
                    name,
                    username,
                    amount: formatCurrency(Number(it.netAmount || 0)),
                    status: it.status || 'completed',
                  };
                })}
                generatedDate={new Date().toISOString()}
              />
            </ViewShot>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#F9FAFB' },
  content: { padding: 16, gap: 16, paddingBottom: 40 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  },
  backButton: {
    padding: 8,
  },
  title: { fontSize: 20, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 13, color: '#6B7280', marginTop: 2 },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  statusText: { fontSize: 12, fontWeight: '700' },

  summaryCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  summaryHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  summaryTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  summaryGrid: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 16,
  },
  summaryItem: {
    flex: 1,
    alignItems: 'center',
    gap: 6,
  },
  summaryDivider: {
    width: 1,
    backgroundColor: '#E5E7EB',
  },
  summaryLabel: { fontSize: 12, color: '#6B7280' },
  summaryValue: { fontSize: 16, fontWeight: '700', color: '#111827' },

  totalAmountCard: {
    backgroundColor: '#ECFDF5',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  totalAmountLabel: { fontSize: 13, color: '#065F46', marginBottom: 4 },
  totalAmountValue: { fontSize: 32, fontWeight: '700', color: '#059669' },
  totalAmountSubtext: { fontSize: 12, color: '#059669', marginTop: 4 },

  sectionHeader: {
    marginTop: 8,
    marginBottom: 12,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  sectionTitle: { fontSize: 16, fontWeight: '700', color: '#111827' },
  sectionSubtitle: { fontSize: 12, color: '#6B7280', marginTop: 4 },

  employeeCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    marginBottom: 12,
  },
  employeeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  employeeIconBadge: {
    width: 40,
    height: 40,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  employeeName: { fontSize: 15, fontWeight: '700', color: '#111827' },
  employeeUsername: { fontSize: 12, color: '#6B7280', marginTop: 2 },
  employeeStatusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  employeeStatusText: { fontSize: 11, fontWeight: '700' },

  employeeDivider: {
    height: 1,
    backgroundColor: '#F3F4F6',
    marginVertical: 12,
  },

  employeeDetails: {
    gap: 8,
  },
  employeeDetailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  employeeDetailLabel: { fontSize: 13, color: '#6B7280', flex: 1 },
  employeeDetailValue: { fontSize: 13, fontWeight: '600', color: '#111827' },

  receiptButton: {
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: '#A7F3D0',
    backgroundColor: '#ECFDF5',
  },
  receiptButtonText: { fontSize: 13, fontWeight: '600', color: '#059669' },

  actionsContainer: {
    marginTop: 8,
    gap: 12,
  },
  primaryButton: {
    backgroundColor: '#059669',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
    shadowColor: '#059669',
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  primaryButtonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  actionsHint: {
    fontSize: 12,
    color: '#9CA3AF',
    textAlign: 'center',
    fontStyle: 'italic',
  },
  hiddenReceipt: {
    position: 'absolute',
    left: -10000,
    top: 0,
  },
});

export default PayrollRunDetailScreen;
