import React, { useRef } from 'react';
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
import { useAuth } from '../contexts/AuthContext';
import { PayrollReceiptView } from '../components/PayrollReceiptView';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollReceipt'>;
type RouteProps = RouteProp<MainStackParamList, 'PayrollReceipt'>;

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
  return d.toLocaleDateString('es', { year: 'numeric', month: '2-digit', day: '2-digit' });
};

export const PayrollReceiptScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const route = useRoute<RouteProps>();
  const transaction = route.params?.transaction as any;
  const { userProfile } = useAuth();
  const viewShotRef = useRef<ViewShot>(null);

  // Determine if this is employee viewing their own receipt
  const isEmployeeView = transaction.direction === 'received';

  const pick = (...vals: any[]) => {
    for (const v of vals) {
      if (v && typeof v === 'string' && v.trim()) return v.trim();
    }
    return '';
  };

  const counterpartyUser = transaction.counterpartyUser || transaction.recipientUser || transaction.senderUser;
  const employeeUsername = pick(
    transaction.employeeUsername,
    counterpartyUser?.username,
    transaction.toUsername,
    transaction.recipientUsername,
    transaction.counterpartyUsername,
    transaction.recipientUser?.username,
    transaction.senderUser?.username,
    userProfile?.username
  );

  const employeeName = pick(
    transaction.employeeName,
    transaction.counterpartyDisplayName,
    transaction.displayCounterparty,
    transaction.to,
    transaction.toName,
    transaction.displayToName,
    `${counterpartyUser?.firstName || ''} ${counterpartyUser?.lastName || ''}`,
    isEmployeeView ? `${userProfile?.firstName || ''} ${userProfile?.lastName || ''}` : '',
    employeeUsername,
    'Empleado'
  );

  const employeePhone = pick(
    transaction.employeePhone,
    counterpartyUser?.phoneKey,
    transaction.toPhone,
    transaction.recipientPhone,
    transaction.counterpartyPhone,
    transaction.recipientUser?.phoneKey,
    transaction.senderUser?.phoneKey,
    userProfile?.phoneKey,
    userProfile?.phone
  );

  const businessName = pick(
    transaction.businessName,
    transaction.from,
    transaction.senderDisplayName,
    transaction.fromName,
    transaction.displayFromName,
    transaction.counterpartyDisplayName,
    transaction.senderUser?.firstName && transaction.senderUser?.lastName ? `${transaction.senderUser.firstName} ${transaction.senderUser.lastName}` : '',
    transaction.senderUser?.username,
    'Empresa'
  );
  const amount = transaction.amount || '0.00';
  const currency = transaction.currency || 'cUSD';
  const date = transaction.date || transaction.executedAt || transaction.createdAt || new Date().toISOString();
  const transactionHash = transaction.hash || transaction.transactionHash || '';
  const payrollRunId = transaction.payrollRunId || transaction.runId || '';
  const status = (transaction.status || 'completed').toLowerCase();

  // Debug log to verify data
  console.log('[PayrollReceipt] Transaction data:', {
    employeeName,
    employeeUsername,
    employeePhone,
    businessName,
    amount,
    rawTransaction: transaction,
  });

  const statusLabel = () => {
    switch (status) {
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

  const handleExportPDF = async () => {
    try {
      if (!viewShotRef.current) {
        Alert.alert('Error', 'El comprobante no está listo para exportar.');
        return;
      }

      // Capture the view as an image
      const uri = await viewShotRef.current.capture();
      if (!uri) {
        throw new Error('No se pudo generar la imagen del comprobante.');
      }

      // Save directly to Camera Roll (complies with Google Play policy)
      const savedUri = await CameraRoll.save(uri, { type: 'photo' });

      Alert.alert(
        'Comprobante guardado',
        'El comprobante se guardó en tu galería de fotos.',
        [
          { text: 'OK' },
          {
            text: 'Compartir',
            onPress: async () => {
              try {
                const message = `Comprobante de pago de nómina - ${employeeName}`;

                await Share.open({
                  title: 'Comprobante de Nómina - Confío',
                  message,
                  url: uri, // Use temp file URI - Works on both iOS and Android with react-native-share
                  type: 'image/jpeg',
                });
              } catch (error) {
                console.error('Share error:', error);
              }
            },
          },
        ]
      );
    } catch (e: any) {
      console.error('Export error', e);
      Alert.alert('Error', 'No se pudo guardar el comprobante. Verifica los permisos de galería.');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={22} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Comprobante de Pago</Text>
        <TouchableOpacity style={styles.downloadButton} onPress={handleExportPDF}>
          <Icon name="download" size={20} color="#059669" />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <ViewShot ref={viewShotRef} options={{ format: 'jpg', quality: 0.9 }}>
          <PayrollReceiptView
            employeeName={employeeName}
            employeeUsername={employeeUsername}
            employeePhone={employeePhone}
            businessName={businessName}
            amount={amount}
            currency={currency}
            date={date}
            status={status}
            transactionHash={transactionHash}
            payrollRunId={payrollRunId}
            generatedDate={new Date().toISOString()}
          />
        </ViewShot>

        {/* Export Button */}
        <TouchableOpacity style={styles.exportButton} onPress={handleExportPDF}>
          <Icon name="download" size={20} color="#fff" />
          <Text style={styles.exportButtonText}>Descargar comprobante</Text>
        </TouchableOpacity>
      </ScrollView>
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
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
    flex: 1,
    marginLeft: 8,
  },
  downloadButton: {
    padding: 8,
  },
  content: {
    paddingBottom: 40,
  },
  exportButton: {
    backgroundColor: '#059669',
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 24,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    margin: 20,
    marginTop: 24,
    shadowColor: '#059669',
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  exportButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },
});

export default PayrollReceiptScreen;
