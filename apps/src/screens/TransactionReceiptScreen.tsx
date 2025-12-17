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
  StatusBar,
} from 'react-native';
import Share from 'react-native-share';
import Icon from 'react-native-vector-icons/Feather';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import ViewShot from 'react-native-view-shot';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { TransactionReceiptView } from '../components/TransactionReceiptView';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'TransactionReceipt'>;
type RouteProps = RouteProp<MainStackParamList, 'TransactionReceipt'>;

export const TransactionReceiptScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const route = useRoute<RouteProps>();
  const transaction = route.params?.transaction as any;
  const viewShotRef = useRef<ViewShot>(null);

  // Infer transaction type if not provided explicitly
  // Note: Future callers should pass { type: 'payroll' | 'payment' | 'transfer' }
  const specifiedType = route.params?.type;
  const isPayroll = specifiedType === 'payroll' || transaction.payrollRunId || transaction.employeeName;
  const isPayment = specifiedType === 'payment' || transaction.invoiceId || transaction.merchantName;

  let type: 'payroll' | 'payment' | 'transfer' = 'transfer';
  if (isPayroll) type = 'payroll';
  else if (isPayment) type = 'payment';

  // Extract Data based on Type
  const pick = (...vals: any[]) => {
    for (const v of vals) {
      if (v && typeof v === 'string' && v.trim()) return v.trim();
    }
    return '';
  };

  const counterpartyUser = transaction.counterpartyUser || transaction.recipientUser || transaction.senderUser;

  // Formatters
  const formatPhoneKey = (phone: string | undefined | null): string => {
    if (!phone) return '';
    if (phone.includes(':')) {
      const [countryCode, phoneNumber] = phone.split(':');
      return `+${countryCode} ${phoneNumber}`;
    }
    return phone;
  };

  // Sender Logic
  let senderName = '';
  let senderLabel = '';
  let senderDetail = '';

  // Recipient Logic
  let recipientName = '';
  let recipientLabel = '';
  let recipientDetail = '';

  let referenceId = '';
  let referenceLabel = '';
  let memo = transaction.memo || transaction.description || '';

  if (type === 'payroll') {
    senderLabel = 'Empresa';
    senderName = pick(transaction.businessName, transaction.fromName, 'Empresa');

    recipientLabel = 'Empleado';
    recipientName = pick(transaction.employeeName, transaction.toName, 'Empleado');
    const rawUsername = pick(transaction.employeeUsername, counterpartyUser?.username, '');
    const empUsername = rawUsername.replace(/^@+/, '');
    const empPhone = formatPhoneKey(pick(transaction.employeePhone, counterpartyUser?.phoneKey));
    recipientDetail = empUsername ? `@${empUsername}` : empPhone;

    referenceLabel = 'ID de corrida';
    referenceId = transaction.payrollRunId || transaction.runId || '';
  } else if (type === 'payment') {
    senderLabel = 'Pagador';
    senderName = pick(transaction.payerName, transaction.senderDisplayName, transaction.fromName, 'Usuario');
    const senderPhone = formatPhoneKey(pick(transaction.payerPhone, transaction.senderPhone));
    senderDetail = senderPhone;

    recipientLabel = 'Comerciante';
    recipientName = pick(transaction.merchantName, transaction.recipientBusiness?.name, 'Comercio');

    referenceLabel = 'Factura';
    referenceId = transaction.invoiceId || '';
  } else {
    // Transfer
    senderLabel = 'Remitente';
    senderName = pick(transaction.senderDisplayName, transaction.fromName, transaction.senderUser?.firstName ? `${transaction.senderUser.firstName} ${transaction.senderUser.lastName}` : '', 'Usuario');
    const sUsername = transaction.senderUser?.username;
    senderDetail = sUsername ? `@${sUsername}` : formatPhoneKey(transaction.senderPhone);

    recipientLabel = 'Destinatario';
    recipientName = pick(transaction.recipientDisplayName, transaction.toName, transaction.recipientUser?.firstName ? `${transaction.recipientUser.firstName} ${transaction.recipientUser.lastName}` : '', 'Usuario');
    const rUsername = transaction.recipientUser?.username;
    recipientDetail = rUsername ? `@${rUsername}` : formatPhoneKey(transaction.recipientPhone);
  }

  const amount = (transaction.amount || '0.00').replace(/^[+-]\s*/, '').replace('cUSD', '').trim();
  const currency = transaction.currency || transaction.tokenType || 'cUSD';
  const date = transaction.date || transaction.executedAt || transaction.createdAt || new Date().toISOString();
  const transactionHash = transaction.hash || transaction.transactionHash || '';
  const status = (transaction.status || 'completed').toLowerCase();

  const handleExportPDF = async () => {
    try {
      if (!viewShotRef.current) return;
      const uri = await viewShotRef.current.capture();
      if (!uri) return;

      await CameraRoll.save(uri, { type: 'photo' });

      Alert.alert(
        'Comprobante guardado',
        'El comprobante se guardó en tu galería.',
        [
          { text: 'OK' },
          {
            text: 'Compartir',
            onPress: async () => {
              try {
                const message = `Comprobante de ${type} - ${amount} ${currency}`;
                await Share.open({
                  title: 'Comprobante',
                  message,
                  url: uri,
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
      Alert.alert('Error', 'No se pudo guardar el comprobante.');
    }
  };

  const getHeaderTitle = () => {
    switch (type) {
      case 'payroll': return 'Recibo de Nómina';
      case 'payment': return 'Recibo de Pago';
      case 'transfer': return 'Recibo de Transferencia';
      default: return 'Recibo de Transacción';
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={22} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>{getHeaderTitle()}</Text>
        <TouchableOpacity style={styles.downloadButton} onPress={handleExportPDF}>
          <Icon name="download" size={20} color="#059669" />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <ViewShot ref={viewShotRef} options={{ format: 'jpg', quality: 0.9 }}>
          <TransactionReceiptView
            type={type}
            senderName={senderName}
            senderLabel={senderLabel}
            senderDetail={senderDetail}
            recipientName={recipientName}
            recipientLabel={recipientLabel}
            recipientDetail={recipientDetail}
            amount={amount}
            currency={currency}
            date={date}
            status={status}
            transactionHash={transactionHash}
            referenceId={referenceId}
            referenceLabel={referenceLabel}
            memo={memo}
            generatedDate={new Date().toISOString()}
          />
        </ViewShot>

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
    marginTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 10 : 0,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
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

export default TransactionReceiptScreen;
