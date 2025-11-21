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
  Modal,
  ActivityIndicator,
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
import { jwtDecode } from 'jwt-decode';
import authService from '../services/authService';
import businessOptInService from '../services/businessOptInService';

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
  const [paymentStatus, setPaymentStatus] = useState<'pending' | 'submitted' | 'paid' | 'expired'>('pending');
  const [hasNavigatedToSuccess, setHasNavigatedToSuccess] = useState(false);
  const [isOptingIn, setIsOptingIn] = useState(false);
  const [optInMessage, setOptInMessage] = useState('Preparando cuenta empresarial...');
  
  // GraphQL mutations and queries
  const [createInvoice] = useMutation(CREATE_INVOICE);
  
  // Poll for invoice status updates when QR is shown
  const { data: invoiceData, refetch: refetchInvoice } = useQuery(GET_INVOICES, {
    skip: !showQRCode || !invoice,
    pollInterval: 3000, // Keep at 3 seconds to avoid server load
    fetchPolicy: 'cache-and-network',
  });

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
        
        // Optimistic: show submitted as soon as the invoice has a SUBMITTED/PENDING_BLOCKCHAIN payment txn
        const hasSubmittedTxn = Array.isArray(currentInvoice.paymentTransactions) && currentInvoice.paymentTransactions.some(
          (pt: any) => pt?.status === 'SUBMITTED' || pt?.status === 'PENDING_BLOCKCHAIN'
        );
        if (hasSubmittedTxn) {
          setPaymentStatus((prev) => {
            if (prev === 'submitted' || prev === 'paid') {
              return prev;
            }
            console.log('ChargeScreen: Payment submitted — waiting for confirmation (stay on Charge screen)');
            return 'submitted';
          });
        }

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
              merchantAddress: activeAccount?.algorandAddress || '',
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
    console.log('ChargeScreen: handleGenerateQR called');
    
    if (!amount || parseFloat(amount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto válido');
      return;
    }

    if (!activeAccount) {
      Alert.alert('Error', 'No se encontró la cuenta activa');
      return;
    }

    console.log('ChargeScreen: Active account:', {
      id: activeAccount.id,
      type: activeAccount.type,
      name: activeAccount.name
    });

    setIsLoading(true);

    try {
      // For business accounts, ensure opt-ins are complete before generating invoice (blocking)
      if (activeAccount.type === 'business') {
        console.log('ChargeScreen: Business account detected, checking opt-ins...');
        
        try {
          const businessOptInService = await import('../services/businessOptInService').then(m => m.default);
          console.log('ChargeScreen: BusinessOptInService imported successfully');
          
          // Show opt-in modal
          setIsOptingIn(true);
          setOptInMessage('Preparando factura...');
          
          const optInSuccess = await businessOptInService.checkAndHandleOptIns(
            // Progress callback to update modal message
            (message: string) => {
              setOptInMessage(message);
            }
          );
          
          console.log('ChargeScreen: Opt-in check result:', optInSuccess);
          
          // Hide opt-in modal
          setIsOptingIn(false);
          
          if (!optInSuccess) {
            console.error('ChargeScreen: Business opt-in failed, cannot generate invoice');
            
            // Check if this is a non-owner employee who can't opt-in
            const token = await authService.getToken();
            const decoded: any = token ? jwtDecode(token) : {};
            const isNonOwnerEmployee = decoded.business_employee_role && decoded.business_employee_role !== 'owner';
            
            if (isNonOwnerEmployee) {
              Alert.alert(
                'Acción requerida del dueño',
                'La cuenta del negocio necesita ser configurada por el dueño. Por favor pide al dueño del negocio que inicie sesión y genere una factura para completar la configuración.',
                [{ text: 'Entendido' }]
              );
            } else {
              Alert.alert(
                'Cuenta no preparada',
                'Tu cuenta empresarial necesita ser configurada para recibir pagos. Por favor intenta de nuevo.',
                [{ text: 'Entendido' }]
              );
            }
            setIsLoading(false);
            return;
          }
          console.log('ChargeScreen: Business opt-ins verified, proceeding with invoice generation');
        } catch (optInError) {
          console.error('ChargeScreen: Error during opt-in check:', optInError);
          setIsOptingIn(false);
          Alert.alert(
            'Error',
            'Error al verificar la cuenta. Por favor intenta de nuevo.',
            [{ text: 'OK' }]
          );
          setIsLoading(false);
          return;
        }
      } else {
        console.log('ChargeScreen: Personal account, skipping opt-in check');
      }
      
      console.log('ChargeScreen: Creating invoice...');
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
        // Trigger an immediate fetch so we don't wait for first poll tick
        try {
          await refetchInvoice();
        } catch (_) {}
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
      case 'submitted':
        return {
          text: 'Pago enviado — esperando confirmación',
          color: '#d97706', // amber-600
          bgColor: '#fef3c7', // amber-100
          icon: 'clock'
        };
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
    <>
      {/* Opt-in Loading Modal */}
      <Modal
        transparent={true}
        animationType="fade"
        visible={isOptingIn}
        onRequestClose={() => {}}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalIconContainer}>
              <Icon name="file-text" size={48} color={colors.primary} />
            </View>
            <Text style={styles.modalTitle}>Generando Factura</Text>
            <Text style={styles.modalMessage}>{optInMessage}</Text>
            <ActivityIndicator size="large" color={colors.primary} style={styles.modalSpinner} />
            <Text style={styles.modalNote}>
              Por favor espera un momento...
            </Text>
          </View>
        </View>
      </Modal>

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
            {activeAccount?.isEmployee && !activeAccount?.employeePermissions?.sendFunds ? (
              <View style={styles.card}>
                <Icon name="lock" size={48} color={colors.primaryText} style={{ alignSelf: 'center', marginBottom: 16 }} />
                <Text style={[styles.cardTitle, { textAlign: 'center' }]}>Función No Disponible</Text>
                <Text style={[styles.cardSubtitle, { textAlign: 'center' }]}>
                  No tienes permisos para realizar pagos desde esta cuenta empresarial.
                </Text>
              </View>
            ) : (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Escanear Código QR para Pagar</Text>
                <Text style={styles.cardSubtitle}>
                  Escanea el código QR de un negocio para realizar un pago de forma rápida y segura
                </Text>
                
                <TouchableOpacity
                  style={[styles.scanButton, { backgroundColor: colors.primary, marginTop: 24 }]}
                  onPress={() => navigation.navigate('Scan', { mode: 'pagar' })}
                >
                  <Icon name="camera" size={20} color="white" style={{ marginRight: 8 }} />
                  <Text style={styles.scanButtonText}>Abrir Escáner QR</Text>
                </TouchableOpacity>
              </View>
            )}
            
            <View style={styles.card}>
              <Text style={styles.cardTitle}>¿Cómo funciona?</Text>
              <Text style={styles.cardSubtitle}>
                • El negocio te mostrará un código QR{'\n'}
                • Presiona "Abrir Escáner QR" arriba{'\n'}
                • Apunta la cámara al código QR{'\n'}
                • Confirma el pago en la siguiente pantalla
              </Text>
            </View>
          </View>
        )}
      </View>
    </ScrollView>
    </>
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
  
  cardSubtitle: {
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 20,
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
  
  // Opt-in Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 20,
    padding: 32,
    alignItems: 'center',
    width: '100%',
    maxWidth: 320,
  },
  modalIconContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  modalMessage: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 20,
  },
  modalSpinner: {
    marginBottom: 20,
  },
  modalNote: {
    fontSize: 12,
    color: '#9ca3af',
    textAlign: 'center',
    fontStyle: 'italic',
  },
});

export { ChargeScreen }; 
