import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  Alert,
  Dimensions,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { BottomTabParamList } from '../types/navigation';
import { useAccountManager } from '../hooks/useAccountManager';

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
  const { activeAccount } = useAccountManager();
  
  const [mode, setMode] = useState('cobrar');
  const [selectedCurrency, setSelectedCurrency] = useState('cUSD');
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [copied, setCopied] = useState(false);
  const [showQRCode, setShowQRCode] = useState(false);

  // Currency configurations
  const currencies = {
    cUSD: {
      name: 'Confío Dollar',
      symbol: 'cUSD',
      color: colors.primary,
      textColor: colors.primaryText,
      icon: 'C'
    },
    CONFIO: {
      name: 'Confío',
      symbol: 'CONFIO',
      color: colors.secondary,
      textColor: colors.secondaryText,
      icon: 'F'
    }
  };

  const currentCurrency = currencies[selectedCurrency as keyof typeof currencies];

  const handleGenerateQR = () => {
    if (amount && parseFloat(amount) > 0) {
      setShowQRCode(true);
    }
  };

  const handleCopy = (text: string) => {
    // In React Native, you'd use Clipboard API
    Alert.alert('Copiado', 'Enlace copiado al portapapeles');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleModeSwitch = (newMode: string) => {
    setMode(newMode);
    setShowQRCode(false);
    setAmount('');
    setDescription('');
  };

  const handleScanPress = () => {
    // Navigate to scan screen
    navigation.navigate('Scan');
  };

  const quickAmounts = ['5.00', '10.00', '25.00', '50.00'];

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
                        <View style={[styles.currencyIcon, { backgroundColor: currencies.cUSD.color }]}>
                          <Text style={styles.currencyIconText}>{currencies.cUSD.icon}</Text>
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
                        <View style={[styles.currencyIcon, { backgroundColor: currencies.CONFIO.color }]}>
                          <Text style={styles.currencyIconText}>{currencies.CONFIO.icon}</Text>
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

                {/* Amount Input */}
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

                {/* Generate Button */}
                <TouchableOpacity
                  style={[
                    styles.generateButton,
                    { backgroundColor: currentCurrency.color },
                    (!amount || parseFloat(amount) <= 0) && styles.generateButtonDisabled
                  ]}
                  onPress={handleGenerateQR}
                  disabled={!amount || parseFloat(amount) <= 0}
                >
                  <Text style={styles.generateButtonText}>Generar Código QR</Text>
                </TouchableOpacity>

                {/* Info */}
                <View style={[
                  styles.infoCard,
                  { backgroundColor: selectedCurrency === 'cUSD' ? colors.primaryLight : '#f3e8ff' }
                ]}>
                  <View style={styles.infoContent}>
                    <Icon 
                      name="maximize" 
                      size={20} 
                      color={selectedCurrency === 'cUSD' ? colors.primaryDark : colors.secondary} 
                      style={styles.infoIcon}
                    />
                    <View style={styles.infoText}>
                      <Text style={[
                        styles.infoTitle,
                        { color: selectedCurrency === 'cUSD' ? colors.primaryDark : colors.secondary }
                      ]}>
                        ¿Cómo funciona?
                      </Text>
                      <Text style={[
                        styles.infoDescription,
                        { color: selectedCurrency === 'cUSD' ? '#065f46' : '#581c87' }
                      ]}>
                        1. Selecciona la moneda y monto{'\n'}
                        2. Genera el código QR{'\n'}
                        3. El cliente escanea y paga{'\n'}
                        4. Recibes el pago instantáneamente
                      </Text>
                    </View>
                  </View>
                </View>
              </>
            ) : (
              <>
                {/* QR Code Display */}
                <View style={styles.card}>
                  <Text style={styles.qrTitle}>Código QR Generado</Text>
                  <Text style={styles.qrSubtitle}>
                    Muestra este código a tu cliente para que pueda pagar
                  </Text>
                  
                  {/* QR Code Placeholder */}
                  <View style={styles.qrCodeContainer}>
                    <Icon name="maximize" size={80} color="#9ca3af" />
                    <Text style={styles.qrCodeText}>Código QR</Text>
                  </View>

                  {/* Payment Details */}
                  <View style={[
                    styles.paymentDetails,
                    { backgroundColor: selectedCurrency === 'cUSD' ? colors.primaryLight : '#f3e8ff' }
                  ]}>
                    <Text style={[
                      styles.paymentAmount,
                      { color: selectedCurrency === 'cUSD' ? colors.primaryDark : colors.secondary }
                    ]}>
                      ${amount} {currentCurrency.symbol}
                    </Text>
                    {description && (
                      <Text style={[
                        styles.paymentDescription,
                        { color: selectedCurrency === 'cUSD' ? '#065f46' : '#581c87' }
                      ]}>
                        {description}
                      </Text>
                    )}
                    <Text style={[
                      styles.paymentId,
                      { color: selectedCurrency === 'cUSD' ? colors.primaryDark : colors.secondary }
                    ]}>
                      ID: PAY{Date.now().toString().slice(-6)}
                    </Text>
                  </View>

                  {/* Actions */}
                  <View style={styles.actionButtons}>
                    <TouchableOpacity 
                      style={styles.actionButton}
                      onPress={() => handleCopy(`confio://pay/${Date.now()}`)}
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
                  }}
                >
                  <Icon name="plus" size={16} color="white" />
                  <Text style={styles.newPaymentButtonText}>Crear nuevo cobro</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        ) : (
          /* Pagar Mode */
          <View style={styles.pagarContent}>
            {/* Scan Area */}
            <View style={styles.card}>
              <Text style={styles.scanTitle}>Escanear Código QR</Text>
              
              {/* QR Scanner Placeholder */}
              <View style={styles.scannerContainer}>
                <Icon name="maximize" size={48} color={colors.primary} />
                <View style={styles.scannerFrame} />
              </View>
              
              <Text style={styles.scanSubtitle}>
                Enfoca el código QR del comerciante para realizar el pago
              </Text>
              
              <View style={styles.scanButtons}>
                <TouchableOpacity 
                  style={[styles.scanButton, { backgroundColor: colors.primary }]}
                  onPress={handleScanPress}
                >
                  <Text style={styles.scanButtonText}>Activar cámara</Text>
                </TouchableOpacity>
                
                <TouchableOpacity style={styles.scanButtonSecondary}>
                  <Text style={styles.scanButtonSecondaryText}>Ingresar código manualmente</Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Payment Info */}
            <View style={[styles.infoCard, { backgroundColor: colors.primaryLight }]}>
              <View style={styles.infoContent}>
                <Icon name="maximize" size={20} color={colors.primaryDark} style={styles.infoIcon} />
                <View style={styles.infoText}>
                  <Text style={[styles.infoTitle, { color: colors.primaryDark }]}>
                    Modo Pago
                  </Text>
                  <Text style={[styles.infoDescription, { color: '#065f46' }]}>
                    Escanea códigos QR de otros comerciantes para pagar por productos o servicios
                  </Text>
                </View>
              </View>
            </View>
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
  },
  currencyIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  currencyIconText: {
    color: 'white',
    fontWeight: 'bold',
    fontSize: 16,
  },
  currencyInfo: {
    flex: 1,
  },
  currencyName: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  currencyNameSelected: {
    color: colors.primaryDark,
  },
  currencySymbol: {
    fontSize: 12,
    color: '#6b7280',
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
});

export { ChargeScreen }; 