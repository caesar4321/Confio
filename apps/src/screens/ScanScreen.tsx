import React, { useState, useCallback, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Dimensions, Alert, Platform, Linking, AppState, AppStateStatus, Modal, StatusBar } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';
import { launchImageLibrary } from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { useAccount } from '../contexts/AccountContext';
import { useRoute, RouteProp, useNavigation, useFocusEffect, useIsFocused } from '@react-navigation/native';
import { BottomTabParamList } from '../types/navigation';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';
import { parseInstitutionLink } from '../utils/institutionLinks';
import { localPaymentQrRoute } from '../utils/localPaymentQr';
import { LOCAL_MONEY_METHODS, LocalMethod } from '../services/localMoney';
import { countryFlag, countryName } from '../config/localRails';

type ScanScreenRouteProp = RouteProp<BottomTabParamList, 'Scan'>;

// The payable QR networks, by the method ids the scan handler routes to.
const QR_RAILS: Record<string, string> = {
  br_qr: 'Pix',
  co_qr: 'Bre-B',
  ar_qr: 'QR Argentina',
};

export const ScanScreen = () => {
  const insets = useSafeAreaInsets();
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [isFlashOn, setIsFlashOn] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [scannedSuccessfully, setScannedSuccessfully] = useState(false);
  const device = useCameraDevice('back');
  const { activeAccount } = useAccount();
  const route = useRoute<ScanScreenRouteProp>();
  const navigation = useNavigation();
  const scanMode = route.params?.mode;

  // Navigation focus state
  const isFocused = useIsFocused();
  // App foreground/background state
  const appState = useRef(AppState.currentState);
  const [isAppActive, setIsAppActive] = useState(appState.current === 'active');

  const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';

  // GraphQL mutations
  const [getInvoice] = useMutation(GET_INVOICE);
  const client = useApolloClient();
  const localScanInFlight = useRef(false);

  // Readiness BEFORE the scan. The scanner used to explain a rail only after
  // a failed scan — at the counter, with the cashier waiting. These chips say
  // up front which QR networks work and, for one that needs a document, take
  // the user to fix it now. The scan handler still re-reads the methods with
  // network-only; this read is for display and decides nothing.
  // Local QR payments are owner-only server-side, so employees get no chips.
  const { data: qrMethodsData, refetch: refetchQrMethods } = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'send' },
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    skip: scanMode === 'cobrar' || !!activeAccount?.isEmployee,
  });
  // A chip sends the user off to verify a document; the tab stays mounted,
  // so re-read on every return or the chip keeps asking after it is done.
  useFocusEffect(
    useCallback(() => {
      if (scanMode === 'cobrar' || activeAccount?.isEmployee) return;
      refetchQrMethods().catch(() => {});
    }, [scanMode, activeAccount?.isEmployee, refetchQrMethods]),
  );
  const qrRails = ((qrMethodsData?.localMoneyMethods || []) as LocalMethod[])
    .filter(m => QR_RAILS[m.id] && ['live', 'needs_verification', 'needs_document'].includes(m.status));
  const liveQrRails = qrRails.filter(m => m.status === 'live');
  const [showRailsSheet, setShowRailsSheet] = useState(false);
  // Read by the scan callback, which can fire in the frame before the camera
  // deactivates.
  const railsSheetOpenRef = useRef(false);
  railsSheetOpenRef.current = showRailsSheet;
  // Pagar tab or the stack screen of the same name (Cobrar, Membresías)?
  const isStackScreen = (navigation as any).getState?.()?.type === 'stack';
  const handleRailChip = (method: LocalMethod) => {
    setShowRailsSheet(false);
    if (method.status === 'needs_verification') {
      (navigation as any).navigate('Verification');
    } else if (method.status === 'needs_document') {
      (navigation as any).navigate('AdditionalDocument', {
        idCountry: method.documentCountry,
        documentTypes: method.documentTypes,
        reason: `Para pagar con ${QR_RAILS[method.id]} en ${countryName(method.country)} necesitamos un documento distinto al que ya verificaste.`,
      });
    }
  };
  const scanSession = useRef(0);

  // Debug logging

  // Monitor AppState to disable camera when app is in background
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextAppState) => {
      appState.current = nextAppState;
      setIsAppActive(nextAppState === 'active');
    });

    return () => {
      subscription.remove();
    };
  }, []);


  useEffect(() => {
    checkPermission();
  }, []);

  const checkPermission = async () => {
    const permission = await Camera.getCameraPermissionStatus();
    if (permission === 'granted') {
      setHasPermission(true);
    } else if (permission === 'denied') {
      Alert.alert(
        'Permiso de cámara requerido',        'Activa el acceso a la cámara en la configuración de tu dispositivo para escanear códigos QR.',
        [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Abrir configuración', onPress: openSettings }
        ]
      );
      setHasPermission(false);
    } else {
      const newPermission = await Camera.requestCameraPermission();
      setHasPermission(newPermission === 'granted');
    }
  };

  const openSettings = () => {
    if (Platform.OS === 'ios') {
      Linking.openURL('app-settings:');
    } else {
      Linking.openSettings();
    }
  };

  const handleQRCodeScanned = async (scannedData: string) => {
    if (isProcessing || localScanInFlight.current || railsSheetOpenRef.current) return;
    const localQr = localPaymentQrRoute(scannedData);
    // EMV payment payloads must never fall through to embedded Confío links.
    if (localQr || scannedData.trim().startsWith('000201')) {
      localScanInFlight.current = true;
      setIsProcessing(true);
      const session = scanSession.current;
      let routed = false;
      let awaitingDismiss = false;
      const showScanError = (title: string, message: string) => {
        awaitingDismiss = true;
        const resume = () => {
          if (scanSession.current !== session) return;
          localScanInFlight.current = false;
          setIsProcessing(false);
          setScannedSuccessfully(false);
        };
        Alert.alert(title, message, [{text: 'Entendido', onPress: resume}], {cancelable: false});
      };
      try {
        if (!localQr) {
          showScanError('Código QR no compatible', 'Este QR de pago no es válido o su país todavía no está disponible.');
          return;
        }
        if (scanMode === 'cobrar') {
          showScanError('QR para pagar', 'Este QR es para enviar un pago. Abre Escanear en modo pagar.');
          return;
        }
        // Local rails are owner-only server-side; stop here rather than walk
        // an employee into LocalSend to fail at the final mutation.
        if (activeAccount?.isEmployee) {
          showScanError('Solo para el dueño', 'Pagar un QR local con dinero del negocio es exclusivo del dueño. Puedes pagar QR de Confío.');
          return;
        }
        const {data} = await client.query({query: LOCAL_MONEY_METHODS,
          variables: {direction: 'send'}, fetchPolicy: 'network-only'});
        if (scanSession.current !== session) return;
        const method: LocalMethod | undefined = data?.localMoneyMethods?.find((m: LocalMethod) => m.id === localQr.methodId);
        if (!['ar_qr', 'br_qr', 'co_qr'].includes(localQr.methodId) || !method
          || !['live', 'needs_verification', 'needs_document'].includes(method.status)) {
          showScanError('Medio no disponible', 'Este tipo de QR todavía no está habilitado para tu cuenta.');
          return;
        }
        // LocalSend retains the payload through KYC/account-opening steps and
        // submits it to server validation. Scanning never authorizes a payment.
        (navigation as any).navigate('LocalSend', {methodId: method.id, scannedQr: scannedData.trim()});
        routed = true;
      } catch {
        if (scanSession.current === session) showScanError('No pudimos revisar este QR', 'Verifica tu conexión e intenta de nuevo.');
      } finally {
        if (scanSession.current === session && !routed && !awaitingDismiss) {
          localScanInFlight.current = false;
          setIsProcessing(false);
          setScannedSuccessfully(false);
        }
      }
      return;
    }
    const institutionLink = parseInstitutionLink(scannedData);
    if (institutionLink) {
      setIsProcessing(true);
      (navigation as any).navigate('Memberships', institutionLink);
      return;
    }


    // Show success indicator
    setScannedSuccessfully(true);

    // Parse the QR code data

    // 1. Check for Verification QR Code (Universal Link or URI Scheme)
    const verifyMatch = scannedData.match(/verify\/([a-zA-Z0-9]+)/);
    if (verifyMatch && verifyMatch[1]) {
      const hash = verifyMatch[1];
      setIsProcessing(true);
      setScannedSuccessfully(true);

      // Navigate to dedicated Verify screen
      setTimeout(() => {
        (navigation as any).navigate('VerifyTransaction', { hash });
        setIsProcessing(false);
        setScannedSuccessfully(false);
      }, 500);
      return;
    }

    // 2. Check for Payment QR Code (Custom Scheme OR Universal Link via HTTPS)
    const schemeMatch = scannedData.match(/^confio:\/\/pay\/(.+)$/);
    const httpsMatch = scannedData.match(/^https:\/\/confio\.lat\/pay\/(.+)$/);
    const validMatch = schemeMatch || httpsMatch;

    if (!validMatch || !validMatch[1]) {
      Alert.alert(
        'Código QR inválido',
        'Escanea un QR de Confío o un QR de pago local compatible.',
        [{ text: 'Entendido', style: 'default' }]
      );
      setScannedSuccessfully(false);
      return;
    }

    const invoiceId = validMatch[1];

    setIsProcessing(true);

    try {
      // SECURITY: Cross-check with server - don't trust QR code data
      // We only use the QR code to get the invoice ID, then fetch real data from server
      const { data: invoiceData } = await getInvoice({
        variables: { invoiceId: invoiceId as string }
      });

      if (!invoiceData?.getInvoice?.success) {
        const errors = invoiceData?.getInvoice?.errors || ['Factura no encontrada'];
        Alert.alert('Error', errors.join(', '), [{ text: 'Entendido' }]);
        return;
      }

      const invoice = invoiceData.getInvoice.invoice;

      // Server-side validations:
      // 1. Invoice exists and is valid
      // 2. Invoice hasn't expired (server checks isExpired)
      // 3. Invoice is still in PENDING status
      if (invoice.isExpired) {
        Alert.alert('Factura expirada', 'Esta solicitud de pago ha expirado.', [{ text: 'Entendido' }]);
        return;
      }

      // Client-side validations:
      // 1. User isn't paying their own invoice
      if (invoice.createdByUser?.id === activeAccount?.id) {
        Alert.alert('Aviso', 'No puedes pagar tu propia factura.', [{ text: 'Entendido' }]);
        setScannedSuccessfully(false);
        return;
      }

      // Navigate to payment confirmation screen
      (navigation as any).navigate('PaymentConfirmation', {
        invoiceData: invoice
      });

    } catch (error) {
      Alert.alert('Error', 'No se pudo procesar el código QR. Intenta de nuevo.', [{ text: 'Entendido' }]);
    } finally {
      setIsProcessing(false);
      setScannedSuccessfully(false);
    }
  };

  useFocusEffect(useCallback(() => {
    scanSession.current += 1;
    localScanInFlight.current = false;
    setIsProcessing(false);
    setScannedSuccessfully(false);
    return () => { scanSession.current += 1; localScanInFlight.current = false; };
  }, [activeAccount?.id]));

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes: Code[]) => {
      // Only scan if focused, active, and not already processing
      if (codes.length > 0 && !isProcessing && isFocused && isAppActive) {
        const scannedData = codes[0].value;
        if (scannedData) {
          handleQRCodeScanned(scannedData);
        }
      }
    },
  });

  const toggleFlash = useCallback(() => {
    setIsFlashOn((current) => !current);
  }, []);

  // Decode a payment QR from a saved photo (screenshot sent by WhatsApp is
  // the common real-world case). Same pipeline as a live scan.
  const handleGallery = useCallback(async () => {
    if (isProcessing) return;
    const session = scanSession.current;
    try {
      const result = await launchImageLibrary({ mediaType: 'photo', selectionLimit: 1 });
      if (session !== scanSession.current) return;
      if (result.didCancel) return;
      if (result.errorCode) {
        Alert.alert('No se pudo abrir la galería', result.errorMessage || result.errorCode, [{ text: 'Entendido' }]);
        return;
      }
      const uri = result.assets?.[0]?.uri;
      if (!uri) return;
      const detected = await RNQRGenerator.detect({ uri });
      if (session !== scanSession.current) return;
      const value = detected?.values?.[0];
      if (value) {
        handleQRCodeScanned(value);
      } else {
        Alert.alert('Sin código QR', 'No se encontró un código QR en la imagen.', [{ text: 'Entendido' }]);
      }
    } catch (e: any) {
      if (session !== scanSession.current) return;
      const msg = String(e?.message || e);
      if (msg.includes('undefined') || msg.includes('null')) {
        // Native module missing from this binary — needs a full rebuild.
        Alert.alert(
          'Función no disponible',
          'Esta versión de la app no incluye el módulo de galería. Reinstala o reconstruye la app.',
          [{ text: 'Entendido' }],
        );
      } else {
        Alert.alert('Sin código QR', 'No se pudo leer un código QR de la imagen.', [{ text: 'Entendido' }]);
      }
    }
  }, [isProcessing, client, navigation, scanMode, activeAccount?.id]);

  // Removed prewarm HEAD /health pings

  const handleClose = () => {
    navigation.goBack();
  };

  if (hasPermission === null) {
    return (
      <View style={styles.container}>
        <Icon name="camera" size={40} color={colors.text.light} />
        <Text style={styles.text}>Solicitando permiso de cámara…</Text>
      </View>
    );
  }

  if (hasPermission === false) {
    return (
      <View style={styles.container}>
        <Icon name="camera-off" size={40} color={colors.text.light} />
        <Text style={styles.text}>Sin acceso a la cámara</Text>
        <Button
          title="Conceder permiso"
          onPress={checkPermission}
          style={{ minWidth: 200 }}
        />
      </View>
    );
  }

  if (!device) {
    return (
      <View style={styles.container}>
        <Icon name="camera-off" size={40} color={colors.text.light} />
        <Text style={styles.text}>No se encontró cámara</Text>
      </View>
    );
  }

  // Calculate if camera should be active
  // STRICT RULE: Only active if screen is focused AND app is in foreground AND not processing a scan
  // This prevents background scanning when payment modal is up
  // The help sheet covers the camera: stop scanning under it, or a QR caught
  // while reading would open a payment behind the sheet.
  const isActive = isFocused && isAppActive && !isProcessing && !showRailsSheet;

  const showRails = scanMode !== 'cobrar' && !activeAccount?.isEmployee;

  return (
    <View style={styles.container}>
      {/* Scoped to focus: the tab stays mounted after leaving it. */}
      {isFocused && <StatusBar barStyle="light-content" backgroundColor="#000000" />}
      <Camera
        style={styles.camera}
        device={device}
        isActive={isActive}
        codeScanner={codeScanner}
        torch={isFlashOn && isActive ? 'on' : 'off'}
        enableZoomGesture
      />

      <View style={styles.overlayAbsolute}>
        {/* Top: one pill that says WHERE a QR works (only rails live for
            this user), plus help. Full-bleed camera: as the Pagar tab there
            is nothing to close; the same screen pushed on the stack (from
            Cobrar or Membresías) has no header and no tabs, so it gets a
            back arrow. */}
        <View style={[styles.topOverlay, { paddingTop: insets.top + 12 }]}>
          <View style={styles.headerControls}>
            {isStackScreen ? (
              <TouchableOpacity style={styles.roundButton} onPress={handleClose} accessibilityRole="button" accessibilityLabel="Volver">
                <Icon name="arrow-left" size={22} color="#FFFFFF" />
              </TouchableOpacity>
            ) : <View style={styles.roundButtonSpacer} />}
            {isBusinessAccount && scanMode ? (
              <View style={styles.modeIndicator}>
                <Text style={styles.modeIndicatorText}>
                  {scanMode === 'cobrar' ? 'Cobrar' : 'Pagar'}
                </Text>
              </View>
            ) : null}
            {showRails ? (
              <TouchableOpacity style={styles.roundButton} onPress={() => setShowRailsSheet(true)} accessibilityRole="button" accessibilityLabel="Qué QR puedo pagar">
                <Icon name="help-circle" size={22} color="#FFFFFF" />
              </TouchableOpacity>
            ) : <View style={styles.roundButtonSpacer} />}
          </View>
          {showRails && (
            <TouchableOpacity
              style={styles.railsPill}
              onPress={() => setShowRailsSheet(true)}
              activeOpacity={0.85}
              accessibilityRole="button"
              accessibilityLabel={liveQrRails.length > 0
                ? `Paga QR en ${liveQrRails.map(m => countryName(m.country)).join(', ')}`
                : 'Qué QR puedo pagar'}
            >
              <Text style={styles.railsPillText}>
                {liveQrRails.length > 0 ? 'Paga QR en' : 'Paga QR con tus dólares'}
              </Text>
              {liveQrRails.map(m => (
                <Text key={m.id} style={styles.railsPillFlag}>{countryFlag(m.country)}</Text>
              ))}
              <Icon name="info" size={15} color="rgba(255,255,255,0.8)" />
            </TouchableOpacity>
          )}
        </View>

        <View style={styles.middleRow}>
          <View style={styles.sideOverlay} />
          <View style={styles.scanFrame}>
            <View style={[styles.corner, styles.cornerTL]} />
            <View style={[styles.corner, styles.cornerTR]} />
            <View style={[styles.corner, styles.cornerBL]} />
            <View style={[styles.corner, styles.cornerBR]} />
            {scannedSuccessfully && (
              <View style={styles.successOverlay}>
                <Icon name="check-circle" size={56} color={colors.primary} />
                <Text style={styles.successText}>Código QR detectado</Text>
              </View>
            )}
          </View>
          <View style={styles.sideOverlay} />
        </View>

        <View style={styles.bottomOverlay}>
          <Text style={styles.instructions}>
            {isProcessing
              ? 'Procesando código QR…'
              : scanMode === 'cobrar'
                ? 'Escanea el código QR del cliente para cobrar'
                : 'Apunta al QR del comercio'}
          </Text>
          {scanMode !== 'cobrar' && !isProcessing && (
            <Text style={styles.instructionsSub}>Verás el monto en tu moneda antes de confirmar</Text>
          )}

          <View style={styles.toolsRow}>
            <TouchableOpacity style={styles.tool} onPress={toggleFlash} accessibilityRole="button" accessibilityLabel={isFlashOn ? 'Apagar linterna' : 'Encender linterna'}>
              <View style={[styles.toolButton, isFlashOn && styles.toolButtonOn]}>
                <Icon name={isFlashOn ? 'zap-off' : 'zap'} size={22} color={isFlashOn ? colors.primaryDeep : colors.white} />
              </View>
              <Text style={styles.toolLabel}>Linterna</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.tool} onPress={handleGallery} accessibilityRole="button" accessibilityLabel="Elegir un código QR desde la galería">
              <View style={styles.toolButton}>
                <Icon name="image" size={22} color={colors.white} />
              </View>
              <Text style={styles.toolLabel}>Galería</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {/* What this scanner pays, per country, with the next step for any
          rail still waiting on a document. Replaces the chips that used to
          crowd the camera. */}
      <Modal visible={showRailsSheet} transparent animationType="slide" onRequestClose={() => setShowRailsSheet(false)}>
        <TouchableOpacity style={styles.sheetBackdrop} activeOpacity={1} onPress={() => setShowRailsSheet(false)}>
          <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 20) }]} onStartShouldSetResponder={() => true}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Paga QR con tus dólares</Text>
            {qrRails.map(method => (
              <TouchableOpacity
                key={method.id}
                style={styles.sheetRow}
                disabled={method.status === 'live'}
                onPress={() => handleRailChip(method)}
                accessibilityRole={method.status === 'live' ? 'text' : 'button'}
                accessibilityLabel={`${QR_RAILS[method.id]}, ${countryName(method.country)}: ${method.status === 'live' ? 'listo' : 'verifica tu documento para pagar'}`}
              >
                <Text style={styles.sheetFlag}>{countryFlag(method.country)}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.sheetRowTitle}>{QR_RAILS[method.id]}</Text>
                  <Text style={styles.sheetRowSub}>{countryName(method.country)}</Text>
                </View>
                {method.status === 'live' ? (
                  <Text style={styles.sheetReady}>Listo</Text>
                ) : (
                  <Text style={styles.sheetPending}>Verificar ›</Text>
                )}
              </TouchableOpacity>
            ))}
            <Text style={styles.sheetNote}>
              Tu saldo se convierte a moneda local al pagar. Ves el tipo de cambio final antes de confirmar.
            </Text>
            <Text style={styles.sheetNote}>También lee los QR de cobro de Confío.</Text>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
};

const { width } = Dimensions.get('window');
const scanFrameSize = width * 0.7;

const DIM = 'rgba(0,0,0,0.55)';
const CORNER = 34;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
    justifyContent: 'center',
    alignItems: 'center',
  },
  camera: {
    ...StyleSheet.absoluteFillObject,
  },
  overlayAbsolute: {
    ...StyleSheet.absoluteFillObject,
  },
  topOverlay: {
    flex: 1,
    backgroundColor: DIM,
    paddingHorizontal: 16,
  },
  headerControls: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  roundButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.35)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  roundButtonSpacer: {
    width: 40,
    height: 40,
  },
  modeIndicator: {
    backgroundColor: 'rgba(0,0,0,0.6)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  modeIndicatorText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  railsPill: {
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 'auto',
    marginBottom: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 22,
    backgroundColor: 'rgba(17,24,39,0.85)',
  },
  railsPillText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
    marginRight: 2,
  },
  railsPillFlag: {
    fontSize: 18,
  },
  middleRow: {
    flexDirection: 'row',
  },
  sideOverlay: {
    flex: 1,
    height: scanFrameSize,
    backgroundColor: DIM,
  },
  scanFrame: {
    width: scanFrameSize,
    height: scanFrameSize,
    alignItems: 'center',
    justifyContent: 'center',
  },
  corner: {
    position: 'absolute',
    width: CORNER,
    height: CORNER,
    borderColor: colors.primary,
  },
  cornerTL: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 22 },
  cornerTR: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 22 },
  cornerBL: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 22 },
  cornerBR: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 22 },
  bottomOverlay: {
    flex: 1.3,
    backgroundColor: DIM,
    alignItems: 'center',
    paddingTop: 20,
  },
  instructions: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '600',
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  instructionsSub: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 13,
    textAlign: 'center',
    marginTop: 6,
    paddingHorizontal: 20,
  },
  toolsRow: {
    flexDirection: 'row',
    gap: 64,
    marginTop: 'auto',
    marginBottom: 20,
  },
  tool: {
    alignItems: 'center',
    gap: 6,
  },
  toolButton: {
    width: 52,
    height: 52,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.16)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolButtonOn: {
    backgroundColor: colors.white,
  },
  toolLabel: {
    color: 'rgba(255,255,255,0.85)',
    fontSize: 12,
  },
  text: {
    color: colors.white,
    fontSize: 16,
    textAlign: 'center',
    marginTop: 12,
    marginBottom: 16,
  },
  successOverlay: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 22,
    padding: 20,
  },
  successText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginTop: 10,
    textAlign: 'center',
  },
  sheetBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingTop: 10,
  },
  sheetHandle: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: 14,
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 8,
  },
  sheetRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
  },
  sheetFlag: {
    fontSize: 24,
  },
  sheetRowTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
  },
  sheetRowSub: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  sheetReady: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  sheetPending: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.warning.text,
  },
  sheetNote: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
    marginTop: 12,
  },
});
