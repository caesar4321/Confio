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
  // FIX: Only infer from props if specifiedType is NOT provided
  const isPayroll = specifiedType
    ? specifiedType === 'payroll'
    : (transaction.payrollRunId || transaction.employeeName);
  const isPayment = specifiedType
    ? specifiedType === 'payment'
    : (transaction.invoiceId || transaction.merchantName);

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
  // Formatters
  const formatPhoneNumber = (phone: string | undefined | null): string => {
    if (!phone) return '';

    // Check for "CC:Number" format (internal Confío format)
    if (phone.includes(':')) {
      const [countryCode, phoneNumber] = phone.split(':');
      return `+${countryCode} ${phoneNumber}`;
    }

    // Check for "CCNumber" format (e.g., CO3001234567) from IOS/server
    const countryCodeMatch = phone.match(/^([A-Z]{2})(.+)$/);
    if (countryCodeMatch) {
      const [, countryPrefix, phoneNumber] = countryCodeMatch;
      const countryDialingCodes: { [key: string]: string } = {
        'US': '1', 'AS': '1', 'DO': '1', 'VE': '58', 'CO': '57',
        'MX': '52', 'AR': '54', 'PE': '51', 'CL': '56', 'EC': '593',
        'BR': '55', 'UY': '598', 'PY': '595', 'BO': '591',
        // Add more as needed
      };

      const dialingCode = countryDialingCodes[countryPrefix];
      if (dialingCode) {
        return `+${dialingCode} ${phoneNumber}`;
      }
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
    senderName = pick(transaction.businessName, transaction.sender_name, transaction.senderName, transaction.fromName, 'Empresa');

    recipientLabel = 'Empleado';
    recipientName = pick(transaction.employeeName, transaction.recipient_name, transaction.recipientName, transaction.toName, 'Empleado');
    const rawUsername = pick(transaction.employeeUsername, counterpartyUser?.username, '');
    const empUsername = rawUsername.replace(/^@+/, '');
    const empPhone = formatPhoneNumber(pick(transaction.employeePhone, counterpartyUser?.phoneKey));
    recipientDetail = empUsername ? `@${empUsername}` : empPhone;

    referenceLabel = 'ID de corrida';
    referenceId = transaction.payrollRunId || transaction.runId || '';
  } else if (type === 'payment') {
    senderLabel = 'Pagador';
    senderName = pick(
      transaction.payerBusiness?.name,
      transaction.payerDisplayName,
      transaction.payerName,
      transaction.senderDisplayName,
      transaction.sender_name,
      transaction.senderName,
      transaction.fromName,
      'Usuario'
    );
    const senderPhone = formatPhoneNumber(pick(transaction.payerPhone, transaction.senderPhone));
    senderDetail = senderPhone;

    recipientLabel = 'Comerciante';
    recipientName = pick(
      transaction.recipientBusiness?.name,
      transaction.merchantName,
      transaction.merchantDisplayName,
      transaction.recipient_name,
      transaction.recipientName,
      'Comercio'
    );

    referenceLabel = 'Factura';
    referenceId = transaction.invoiceId || '';
  } else {
    // Transfer
    senderLabel = 'Remitente';
    senderName = pick(
      transaction.senderDisplayName,
      transaction.sender_name,
      transaction.senderName,
      transaction.fromName,
      transaction.senderUser?.firstName ? `${transaction.senderUser.firstName} ${transaction.senderUser.lastName}` : '',
      transaction.senderAddress ? `Externo (${transaction.senderAddress.slice(0, 4)}...${transaction.senderAddress.slice(-4)})` : '',
      'Billetera Externa'
    );
    const sUsername = transaction.senderUser?.username;
    const sAddr = transaction.senderAddress || transaction.fromAddress;
    senderDetail = sUsername
      ? `@${sUsername}`
      : (formatPhoneNumber(transaction.senderPhone) || (sAddr ? `${sAddr.slice(0, 6)}...${sAddr.slice(-6)}` : ''));

    recipientLabel = 'Destinatario';
    recipientName = pick(
      transaction.recipientDisplayName,
      transaction.recipient_name,
      transaction.recipientName,
      transaction.toName,
      transaction.recipientUser?.firstName ? `${transaction.recipientUser.firstName} ${transaction.recipientUser.lastName}` : '',
      'Usuario'
    );
    const rUsername = transaction.recipientUser?.username;
    recipientDetail = rUsername ? `@${rUsername}` : formatPhoneNumber(transaction.recipientPhone);
  }

  const amount = (transaction.amount || '0.00').replace(/^[+-]\s*/, '').replace('cUSD', '').trim();
  const currency = transaction.currency || transaction.tokenType || 'cUSD';
  const date = transaction.date || transaction.executedAt || transaction.createdAt || new Date().toISOString();
  const transactionHash = transaction.hash || transaction.transactionHash || '';
  // FIX: Strictly use verificationId or internal id. NEVER use transaction hash for verification.
  // If no valid internal ID exists, verificationId should be falsy, checking for length to avoid 'undefined' string
  const rawId = transaction.verificationId || transaction.id || transaction.internalId || transaction.internal_id;
  // Ensure it's a UUID/Internal ID (not a hash)
  const isHash = typeof rawId === 'string' && rawId.startsWith('0x');
  const verificationId = (!isHash && rawId) ? rawId : undefined;
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
                let spanishType = 'Transacción';
                if (type === 'payroll') spanishType = 'Nómina';
                else if (type === 'payment') spanishType = 'Pago';
                else if (type === 'transfer') spanishType = 'Transferencia';

                const message = `Comprobante de ${spanishType} - ${amount} ${currency}`;
                await Share.open({
                  title: `Comprobante de ${spanishType}`,
                  message,
                  url: uri,
                  type: 'image/jpeg',
                  filename: `Comprobante_${spanishType}_${transaction.id || 'confio'}`,
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
            verificationId={verificationId}
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
