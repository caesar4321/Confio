import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  Alert,
  Dimensions,
  Image,
  Platform,
  Linking,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { BottomTabParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useMutation, useQuery } from '@apollo/client';
import { CREATE_INVOICE, GET_INVOICES, GET_INVOICE } from '../apollo/queries';
import QRCode from 'react-native-qrcode-svg';
import { Clipboard } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';

// Import currency icons
const cUSDIcon = require('../assets/png/cUSD.png');
const CONFIOIcon = require('../assets/png/CONFIO.png');

type ChargeScreenNavigationProp = BottomTabNavigationProp<BottomTabParamList, 'Charge'>;

const { width } = Dimensions.get('window');

// Color palette from the original design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

const ChargeScreen = () => {
  const navigation = useNavigation<ChargeScreenNavigationProp>();
  const { activeAccount } = useAccount();
  
  const [mode, setMode] = useState('cobrar');
  const [selectedCurrency, setSelectedCurrency] = useState('cUSD');
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [copied, setCopied] = useState(false);
  const [showQRCode, setShowQRCode] = useState(false);
  const [invoice, setInvoice] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState<'pending' | 'paid' | 'expired'>('pending');
  const [hasNavigatedToSuccess, setHasNavigatedToSuccess] = useState(false);
  
  // Camera states for pagar mode
  const [hasCameraPermission, setHasCameraPermission] = useState<boolean | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [scannedSuccessfully, setScannedSuccessfully] = useState(false);
  const device = useCameraDevice('back');

  // GraphQL mutations and queries
  const [createInvoice] = useMutation(CREATE_INVOICE);
  const [getInvoice] = useMutation(GET_INVOICE);
  
  // Poll for invoice status updates when QR is shown
  const { data: invoiceData, refetch: refetchInvoice } = useQuery(GET_INVOICES, {
    skip: !showQRCode || !invoice,
    pollInterval: 3000, // Poll every 3 seconds for real-time updates
    fetchPolicy: 'cache-and-network',
  });

  // Camera permission check
  useEffect(() => {
    if (mode === 'pagar') {
      checkCameraPermission();
    }
  }, [mode]);

  const checkCameraPermission = async () => {
    const permission = await Camera.getCameraPermissionStatus();
    if (permission === 'granted') {
      setHasCameraPermission(true);
    } else if (permission === 'denied') {
      Alert.alert(
        'Camera Permission Required',
        'Please enable camera access in your device settings to use the QR code scanner.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open Settings', onPress: openSettings }
        ]
      );
      setHasCameraPermission(false);
    } else {
      const newPermission = await Camera.requestCameraPermission();
      setHasCameraPermission(newPermission === 'granted');
    }
  };

  const openSettings = () => {
    if (Platform.OS === 'ios') {
      Linking.openURL('app-settings:');
    } else {
      Linking.openSettings();
    }
  };

  // QR Code scanner configuration
  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes: Code[]) => {
      if (codes.length > 0 && !isProcessing && codes[0].value) {
        handleQRCodeScanned(codes[0].value);
      }
    },
  });

  const handleQRCodeScanned = async (scannedData: string) => {
    if (isProcessing) return; // Prevent multiple processing
    
    console.log('QR Code scanned:', scannedData);
    
    // Show success indicator
    setScannedSuccessfully(true);
    
    // Parse the QR code data
    const qrMatch = scannedData.match(/^confio:\/\/pay\/(.+)$/);
    if (!qrMatch || !qrMatch[1]) {
      Alert.alert(
        'Invalid QR Code',
        'This QR code is not a valid Confío payment code.',
        [{ text: 'OK', style: 'default' }]
      );
      setScannedSuccessfully(false);
      return;
    }

    const invoiceId = qrMatch[1]!; // Use non-null assertion since we already checked it exists
    console.log('Invoice ID extracted:', invoiceId);

    setIsProcessing(true);

    try {
      // SECURITY: Cross-check with server - don't trust QR code data
      // We only use the QR code to get the invoice ID, then fetch real data from server
      const { data: invoiceData } = await getInvoice({
        variables: { invoiceId }
      });

      if (!invoiceData?.getInvoice?.success) {
        const errors = invoiceData?.getInvoice?.errors || ['Invoice not found'];
        Alert.alert('Error', errors.join(', '));
        return;
      }

      const invoice = invoiceData.getInvoice.invoice;
      console.log('Invoice details:', invoice);

      // Server-side validations:
      // 1. Invoice exists and is valid
      // 2. Invoice hasn't expired (server checks isExpired)
      // 3. Invoice is still in PENDING status
      if (invoice.isExpired) {
        Alert.alert('Invoice Expired', 'This payment request has expired.');
        return;
      }

      // Client-side validations:
      // 1. User isn't paying their own invoice
      if (invoice.merchantUser?.id === activeAccount?.id) {
        Alert.alert('Cannot Pay Own Invoice', 'You cannot pay your own invoice.');
        setScannedSuccessfully(false);
        return;
      }

      // Navigate to payment confirmation screen
      (navigation as any).navigate('PaymentConfirmation', {
        invoiceData: invoice
      });
    } catch (error) {
      console.error('Error processing QR code:', error);
      Alert.alert('Error', 'Failed to process QR code. Please try again.');
    } finally {
      setIsProcessing(false);
      setScannedSuccessfully(false);
    }
  };

  // Check for payment status updates
  useEffect(() => {
    if (showQRCode && invoice && invoiceData?.invoices) {
      console.log('ChargeScreen: Checking for payment status updates...');
      console.log('ChargeScreen: Current invoice ID:', invoice.invoiceId);
      console.log('ChargeScreen: Available invoices:', invoiceData.invoices.map((inv: any) => ({ id: inv.invoiceId, status: inv.status })));
      
      const currentInvoice = invoiceData.invoices.find((inv: any) => inv.invoiceId === invoice.invoiceId);
      if (currentInvoice) {
        console.log('ChargeScreen: Found current invoice:', {
          id: currentInvoice.invoiceId,
          status: currentInvoice.status,
          paidByUser: currentInvoice.paidByUser,
          transaction: currentInvoice.transaction
        });
        
        if (currentInvoice.status === 'PAID' && !hasNavigatedToSuccess) {
          console.log('ChargeScreen: Payment confirmed! Navigating to BusinessPaymentSuccess...');
          setPaymentStatus('paid');
          setHasNavigatedToSuccess(true);
          
          // Automatically navigate to business payment success screen
          (navigation as any).navigate('BusinessPaymentSuccess', {
            paymentData: {
              id: currentInvoice.id,
              paymentTransactionId: currentInvoice.paymentTransactions?.[0]?.paymentTransactionId || currentInvoice.invoiceId,
              amount: currentInvoice.amount,
              tokenType: currentInvoice.tokenType,
              description: currentInvoice.description,
              payerUser: currentInvoice.paidByUser || {
                id: '',
                username: 'Cliente',
                firstName: undefined,
                lastName: undefined
              },
              payerAccount: currentInvoice.paymentTransactions?.[0]?.payerAccount,
              payerAddress: currentInvoice.paymentTransactions?.[0]?.payerAddress || '0x...',
              merchantUser: {
                id: activeAccount?.id || '',
                username: activeAccount?.name || 'Tu Negocio',
                firstName: undefined,
                lastName: undefined
              },
              merchantAccount: currentInvoice.merchantAccount,
              merchantAddress: activeAccount?.suiAddress || '0x...',
              status: currentInvoice.status,
              transactionHash: currentInvoice.paymentTransactions?.[0]?.transactionHash || 'pending',
              createdAt: currentInvoice.paidAt || new Date().toISOString()
            }
          });
        } else if (currentInvoice.isExpired) {
          console.log('ChargeScreen: Invoice expired');
          setPaymentStatus('expired');
        } else {
          console.log('ChargeScreen: Invoice still pending, status:', currentInvoice.status);
        }
      } else {
        console.log('ChargeScreen: Current invoice not found in polled data');
      }
    }
  }, [invoiceData, showQRCode, invoice, navigation, activeAccount]);

  // Currency configurations
  const currencies = {
    cUSD: {
      name: 'Confío Dollar',
      symbol: 'cUSD',
      color: colors.primary,
      textColor: colors.primaryText,
      icon: cUSDIcon
    },
    CONFIO: {
      name: 'Confío',
      symbol: 'CONFIO',
      color: colors.secondary,
      textColor: colors.secondaryText,
      icon: CONFIOIcon
    }
  };

  const currentCurrency = currencies[selectedCurrency as keyof typeof currencies];

  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency;
  };

  const handleGenerateQR = async () => {
    if (!amount || parseFloat(amount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto válido');
      return;
    }

    if (!activeAccount) {
      Alert.alert('Error', 'No se encontró la cuenta activa');
      return;
    }

    setIsLoading(true);

    try {
      const { data } = await createInvoice({
        variables: {
          input: {
            amount: amount,
            tokenType: selectedCurrency,
            description: description,
            expiresInHours: 24
          }
        }
      });

      if (data?.createInvoice?.success) {
        const newInvoice = data.createInvoice.invoice;
        setInvoice(newInvoice);
        setShowQRCode(true);
        setPaymentStatus('pending');
        setHasNavigatedToSuccess(false);
      } else {
        const errors = data?.createInvoice?.errors || ['Error desconocido'];
        Alert.alert('Error', errors.join(', '));
      }
    } catch (error) {
      console.error('Error creating invoice:', error);
      Alert.alert('Error', 'No se pudo crear la factura. Inténtalo de nuevo.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = (text: string) => {
    Clipboard.setString(text);
    Alert.alert('Copiado', 'Enlace copiado al portapapeles');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleModeSwitch = (newMode: string) => {
    setMode(newMode);
    setShowQRCode(false);
    setAmount('');
    setDescription('');
    setInvoice(null);
    setPaymentStatus('pending');
    setHasNavigatedToSuccess(false);
  };



  const quickAmounts = ['5.00', '10.00', '25.00', '50.00'];

  // Get status display info
  const getStatusInfo = () => {
    switch (paymentStatus) {
      case 'paid':
        return {
          text: '¡Pago Confirmado!',
          color: '#059669',
          bgColor: '#d1fae5',
          icon: 'check-circle'
        };
      case 'expired':
        return {
          text: 'Factura Expirada',
          color: '#dc2626',
          bgColor: '#fee2e2',
          icon: 'clock'
        };
      default:
        return {
          text: 'Esperando Pago...',
          color: '#d97706',
          bgColor: '#fef3c7',
          icon: 'clock'
        };
    }
  };

  const statusInfo = getStatusInfo();

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      {/* Header */}
      <View style={[
        styles.header,
        { backgroundColor: mode === 'cobrar' ? currentCurrency.color : colors.primary }
      ]}>
        <View style={styles.headerContent}>
          <View style={styles.qrIconContainer}>
            <Icon name="maximize" size={32} color={mode === 'cobrar' ? currentCurrency.color : colors.primary} />
          </View>
          <Text style={styles.headerTitle}>
            {mode === 'cobrar' ? 'Cobrar' : 'Pagar'}
          </Text>
          <Text style={styles.headerSubtitle}>
            {mode === 'cobrar' 
              ? 'Genera códigos QR para recibir pagos de tus clientes'
              : 'Escanea códigos QR para realizar pagos'
            }
          </Text>
        </View>
      </View>

      {/* Mode Toggle */}
      <View style={styles.modeToggleContainer}>
        <View style={styles.modeToggle}>
          <TouchableOpacity
            style={[
              styles.modeButton,
              mode === 'cobrar' && { backgroundColor: currentCurrency.color }
            ]}
            onPress={() => handleModeSwitch('cobrar')}
          >
            <Text style={[
              styles.modeButtonText,
              mode === 'cobrar' && styles.modeButtonTextActive
            ]}>
              Cobrar
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.modeButton,
              mode === 'pagar' && { backgroundColor: colors.primary }
            ]}
            onPress={() => handleModeSwitch('pagar')}
          >
            <Text style={[
              styles.modeButtonText,
              mode === 'pagar' && styles.modeButtonTextActive
            ]}>
              Pagar
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Content */}
      <View style={styles.content}>
        {mode === 'cobrar' ? (
          <View style={styles.cobrarContent}>
            {!showQRCode ? (
              <>
                {/* Currency Selector */}
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Moneda para cobrar</Text>
                  <View style={styles.currencyGrid}>
                    <TouchableOpacity
                      style={[
                        styles.currencyButton,
                        selectedCurrency === 'cUSD' && styles.currencyButtonSelected
                      ]}
                      onPress={() => setSelectedCurrency('cUSD')}
                    >
                      <View style={styles.currencyContent}>
                        <View style={styles.currencyIcon}>
                          <Image source={currencies.cUSD.icon} style={styles.currencyIconImage} />
                        </View>
                        <View style={styles.currencyInfo}>
                          <Text style={[
                            styles.currencyName,
                            selectedCurrency === 'cUSD' && styles.currencyNameSelected
                          ]}>
                            {currencies.cUSD.name}
                          </Text>
                          <Text style={[
                            styles.currencySymbol,
                            selectedCurrency === 'cUSD' && styles.currencySymbolSelected
                          ]}>
                            ${currencies.cUSD.symbol}
                          </Text>
                        </View>
                      </View>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.currencyButton,
                        selectedCurrency === 'CONFIO' && styles.currencyButtonSelected
                      ]}
                      onPress={() => setSelectedCurrency('CONFIO')}
                    >
                      <View style={styles.currencyContent}>
                        <View style={styles.currencyIcon}>
                          <Image source={currencies.CONFIO.icon} style={styles.currencyIconImage} />
                        </View>
                        <View style={styles.currencyInfo}>
                          <Text style={[
                            styles.currencyName,
                            selectedCurrency === 'CONFIO' && styles.currencyNameSelected
                          ]}>
                            {currencies.CONFIO.name}
                          </Text>
                          <Text style={[
                            styles.currencySymbol,
                            selectedCurrency === 'CONFIO' && styles.currencySymbolSelected
                          ]}>
                            ${currencies.CONFIO.symbol}
                          </Text>
                        </View>
                      </View>
                    </TouchableOpacity>
                  </View>
                </View>

                {/* Payment Request Form */}
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Solicitar Pago</Text>
                  
                  <View style={styles.inputContainer}>
                    <Text style={styles.inputLabel}>Monto a cobrar</Text>
                    <View style={styles.amountInputContainer}>
                      <Icon name="dollar-sign" size={20} color="#9ca3af" style={styles.amountInputIcon} />
                      <TextInput
                        style={styles.amountInput}
                        value={amount}
                        onChangeText={setAmount}
                        placeholder="0.00"
                        keyboardType="numeric"
                        placeholderTextColor="#9ca3af"
                      />
                      <Text style={[styles.currencyLabel, { color: currentCurrency.color }]}>
                        {currentCurrency.symbol}
                      </Text>
                    </View>
                  </View>

                  <View style={styles.inputContainer}>
                    <Text style={styles.inputLabel}>Descripción (opcional)</Text>
                    <TextInput
                      style={styles.descriptionInput}
                      value={description}
                      onChangeText={setDescription}
                      placeholder="Ej: Almuerzo, Corte de cabello, Mesa 5..."
                      maxLength={50}
                    />
                    <Text style={styles.characterCount}>
                      {description.length}/50 caracteres
                    </Text>
                  </View>

                  {/* Quick Amount Buttons */}
                  <View style={styles.quickAmountsContainer}>
                    <Text style={styles.quickAmountsLabel}>Montos rápidos:</Text>
                    <View style={styles.quickAmountsGrid}>
                      {quickAmounts.map((quickAmount) => (
                        <TouchableOpacity
                          key={quickAmount}
                          style={styles.quickAmountButton}
                          onPress={() => setAmount(quickAmount)}
                        >
                          <Text style={styles.quickAmountText}>${quickAmount}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  </View>

                  <TouchableOpacity
                    style={[
                      styles.generateButton,
                      { backgroundColor: currentCurrency.color },
                      isLoading && styles.generateButtonDisabled
                    ]}
                    onPress={handleGenerateQR}
                    disabled={isLoading}
                  >
                    <Text style={styles.generateButtonText}>
                      {isLoading ? 'Generando...' : 'Generar Código QR'}
                    </Text>
                  </TouchableOpacity>
                </View>

                {/* Info Card */}
                <View style={[styles.card, styles.infoCard]}>
                  <View style={styles.infoContent}>
                    <Icon name="info" size={20} color={currentCurrency.color} style={styles.infoIcon} />
                    <View style={styles.infoText}>
                      <Text style={styles.infoTitle}>¿Cómo funciona?</Text>
                      <Text style={styles.infoDescription}>
                        Genera un código QR único para cada pago. Tu cliente escanea el código y confirma el pago. Recibirás una notificación inmediata cuando se complete la transacción.
                      </Text>
                    </View>
                  </View>
                </View>
              </>
            ) : (
              <>
                {/* QR Code Display with Real-time Status */}
                <View style={styles.card}>
                  <Text style={styles.qrTitle}>Código QR de Pago</Text>
                  <Text style={styles.qrSubtitle}>
                    Comparte este código con tu cliente para recibir el pago
                  </Text>
                  
                  {/* Real-time Status Badge */}
                  <View style={[styles.statusBadge, { backgroundColor: statusInfo.bgColor }]}>
                    <Icon name={statusInfo.icon as any} size={16} color={statusInfo.color} style={styles.statusIcon} />
                    <Text style={[styles.statusText, { color: statusInfo.color }]}>
                      {statusInfo.text}
                    </Text>
                  </View>

                  <View style={styles.qrCodeContainer}>
                    <QRCode
                      value={invoice?.qrCodeData || `confio://pay/${Date.now()}`}
                      size={200}
                      color="#000000"
                      backgroundColor="#FFFFFF"
                    />
                  </View>
                  
                  <Text style={styles.qrCodeText}>
                    ID: {invoice?.invoiceId || 'Generando...'}
                  </Text>

                  <View style={[styles.paymentDetails, { backgroundColor: currentCurrency.color + '10' }]}>
                    <Text style={[styles.paymentAmount, { color: currentCurrency.color }]}>
                      ${invoice?.amount || amount} {formatCurrency(invoice?.tokenType || selectedCurrency)}
                    </Text>
                    <Text style={styles.paymentDescription}>
                      {invoice?.description || description || 'Sin descripción'}
                    </Text>
                    <Text style={styles.paymentId}>
                      Válido por 24 horas
                    </Text>
                  </View>

                  <View style={styles.actionButtons}>
                    <TouchableOpacity 
                      style={styles.actionButton}
                      onPress={() => handleCopy(invoice?.qrCodeData || `confio://pay/${Date.now()}`)}
                    >
                      <Icon name={copied ? "check-circle" : "copy"} size={16} color="#374151" />
                      <Text style={styles.actionButtonText}>
                        {copied ? 'Copiado' : 'Copiar enlace de pago'}
                      </Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity style={styles.actionButton}>
                      <Icon name="share" size={16} color="#374151" />
                      <Text style={styles.actionButtonText}>Compartir código QR</Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity style={styles.actionButton}>
                      <Icon name="download" size={16} color="#374151" />
                      <Text style={styles.actionButtonText}>Descargar imagen</Text>
                    </TouchableOpacity>
                  </View>
                </View>

                {/* New Payment Button */}
                <TouchableOpacity
                  style={[styles.newPaymentButton, { backgroundColor: currentCurrency.color }]}
                  onPress={() => {
                    setShowQRCode(false);
                    setAmount('');
                    setDescription('');
                    setInvoice(null);
                    setPaymentStatus('pending');
                  }}
                >
                  <Icon name="plus" size={16} color="white" />
                  <Text style={styles.newPaymentButtonText}>Crear nuevo cobro</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        ) : (
          <View style={styles.pagarContent}>
            {hasCameraPermission === null ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Solicitando Permiso de Cámara</Text>
                <Text style={styles.cardSubtitle}>Por favor espera mientras solicitamos acceso a la cámara...</Text>
              </View>
            ) : hasCameraPermission === false ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Permiso de Cámara Requerido</Text>
                <Text style={styles.cardSubtitle}>
                  Necesitamos acceso a la cámara para escanear códigos QR. Por favor habilita el acceso en la configuración de tu dispositivo.
                </Text>
                <TouchableOpacity
                  style={[styles.scanButton, { backgroundColor: colors.primary, marginTop: 16 }]}
                  onPress={checkCameraPermission}
                >
                  <Text style={styles.scanButtonText}>Solicitar Permiso</Text>
                </TouchableOpacity>
              </View>
            ) : !device ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Cámara No Disponible</Text>
                <Text style={styles.cardSubtitle}>No se pudo acceder a la cámara del dispositivo.</Text>
              </View>
            ) : (
              <>
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Escanear Código QR</Text>
                  <Text style={styles.cardSubtitle}>
                    Escanea el código QR de un negocio para realizar un pago
                  </Text>
                </View>
                
                <View style={styles.cameraContainer}>
                  <Camera
                    style={styles.camera}
                    device={device}
                    isActive={true}
                    codeScanner={codeScanner}
                    enableZoomGesture
                  >
                    <View style={styles.cameraOverlay}>
                      <View style={styles.scanFrame} />
                      {scannedSuccessfully && (
                        <View style={styles.successOverlay}>
                          <Icon name="check-circle" size={60} color="#10B981" />
                          <Text style={styles.successText}>Código QR detectado</Text>
                        </View>
                      )}
                    </View>
                  </Camera>
                </View>
                
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Instrucciones</Text>
                  <Text style={styles.cardSubtitle}>
                    • Coloca el código QR dentro del marco{'\n'}
                    • Mantén la cámara estable{'\n'}
                    • El código se detectará automáticamente
                  </Text>
                </View>
              </>
            )}
          </View>
        )}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  header: {
    paddingTop: 60,
    paddingBottom: 24,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  qrIconContainer: {
    width: 64,
    height: 64,
    backgroundColor: 'white',
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  headerSubtitle: {
    fontSize: 14,
    color: 'white',
    opacity: 0.8,
    textAlign: 'center',
  },
  modeToggleContainer: {
    paddingHorizontal: 16,
    marginTop: -8,
    marginBottom: 24,
  },
  modeToggle: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 4,
    flexDirection: 'row',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  modeButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  modeButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#4b5563',
    textAlign: 'center',
  },
  modeButtonTextActive: {
    color: 'white',
  },
  content: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  cobrarContent: {
    gap: 24,
  },
  pagarContent: {
    gap: 24,
  },
  card: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 16,
  },
  currencyGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  currencyButton: {
    flex: 1,
    padding: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    backgroundColor: colors.neutralDark,
  },
  currencyButtonSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primaryLight,
  },
  currencyContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  currencyIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
    backgroundColor: 'transparent',
  },
  currencyIconImage: {
    width: 32,
    height: 32,
    resizeMode: 'contain',
  },
  currencyInfo: {
    alignItems: 'center',
    minWidth: 80,
  },
  currencyName: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#1f2937',
    textAlign: 'center',
  },
  currencyNameSelected: {
    color: colors.primaryDark,
  },
  currencySymbol: {
    fontSize: 12,
    color: '#6b7280',
    textAlign: 'center',
  },
  currencySymbolSelected: {
    color: colors.primaryDark,
  },
  inputContainer: {
    marginBottom: 16,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 8,
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutralDark,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 12,
  },
  amountInputIcon: {
    marginRight: 8,
  },
  amountInput: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    paddingVertical: 16,
    color: '#1f2937',
  },
  currencyLabel: {
    fontSize: 16,
    fontWeight: '600',
  },
  descriptionInput: {
    backgroundColor: colors.neutralDark,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    padding: 12,
    fontSize: 16,
    color: '#1f2937',
  },
  characterCount: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 4,
  },
  quickAmountsContainer: {
    marginTop: 16,
    marginBottom: 24,
  },
  quickAmountsLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 8,
  },
  quickAmountsGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  quickAmountButton: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 12,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
    alignItems: 'center',
  },
  quickAmountText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
  },
  generateButton: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  generateButtonDisabled: {
    opacity: 0.5,
  },
  generateButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: 'white',
  },
  infoCard: {
    padding: 16,
    borderRadius: 12,
  },
  infoContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  infoIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  infoText: {
    flex: 1,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 4,
  },
  infoDescription: {
    fontSize: 12,
    lineHeight: 16,
  },
  qrTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    textAlign: 'center',
    marginBottom: 8,
  },
  qrSubtitle: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    marginBottom: 24,
  },
  qrCodeContainer: {
    width: 256,
    height: 256,
    backgroundColor: colors.neutralDark,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    marginBottom: 24,
  },
  qrCodeText: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 8,
  },
  paymentDetails: {
    padding: 16,
    borderRadius: 12,
    marginBottom: 24,
    alignItems: 'center',
  },
  paymentAmount: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  paymentDescription: {
    fontSize: 14,
    marginBottom: 8,
  },
  paymentId: {
    fontSize: 12,
  },
  actionButtons: {
    gap: 12,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
  },
  actionButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    marginLeft: 8,
  },
  newPaymentButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
  },
  newPaymentButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: 'white',
    marginLeft: 8,
  },
  scanTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    textAlign: 'center',
    marginBottom: 16,
  },
  scannerContainer: {
    width: 256,
    height: 256,
    backgroundColor: colors.dark,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    marginBottom: 24,
    position: 'relative',
  },
  scannerFrame: {
    position: 'absolute',
    width: 224,
    height: 224,
    borderWidth: 2,
    borderColor: colors.primary,
    borderRadius: 8,
  },
  scanSubtitle: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    marginBottom: 16,
  },
  scanButtons: {
    gap: 12,
  },
  scanButton: {
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
  },
  scanButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: 'white',
  },
  scanButtonSecondary: {
    paddingVertical: 12,
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    alignItems: 'center',
  },
  scanButtonSecondaryText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
  },
  
  // New styles for camera functionality
  cardSubtitle: {
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 20,
  },
  cameraContainer: {
    width: '100%',
    height: 300,
    borderRadius: 16,
    overflow: 'hidden',
    marginBottom: 24,
  },
  camera: {
    flex: 1,
  },
  cameraOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scanFrame: {
    width: 250,
    height: 250,
    borderWidth: 2,
    borderColor: colors.primary,
    borderRadius: 12,
    backgroundColor: 'transparent',
  },
  successOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  successText: {
    fontSize: 16,
    fontWeight: '600',
    color: 'white',
    marginTop: 16,
  },
  
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 12,
    marginBottom: 16,
  },
  statusIcon: {
    marginRight: 8,
  },
  statusText: {
    fontSize: 14,
    fontWeight: '600',
  },
});

export { ChargeScreen }; 