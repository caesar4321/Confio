import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Platform,
  Share,
  Clipboard,
  Alert,
  StatusBar,
  Image,
} from 'react-native';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import { Header } from '../navigation/Header';
import ViewShot from 'react-native-view-shot';

const colors = {
  primary: '#00d4aa',
  primaryDark: '#00b894',
  background: '#f8f9fa',
  white: '#ffffff',
  text: '#333333',
  textLight: '#666666',
  border: '#e9ecef',
  warning: '#fff3cd',
  warningBorder: '#ffeaa7',
  warningText: '#856404',
  info: '#e8f4f8',
  infoText: '#0c5460',
};

export const ConfioAddressScreen = () => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const { userProfile } = useAuth();
  const [hasSharedBefore, setHasSharedBefore] = useState(false);
  const username = userProfile?.username ? `@${userProfile.username}` : '@usuario';
  const addressUrl = userProfile?.username ? `https://confio.lat/@${userProfile.username}` : 'https://confio.lat/@usuario';
  const qrRef = useRef<ViewShot>(null);

  const handleShare = async () => {
    if (!hasSharedBefore) {
      Alert.alert(
        'Recuerda',
        'Esta dirección es para uso personal. Los comercios deben usar "Pagar" para recibir pagos formales y tener soporte y facturación.',
        [
          {
            text: 'Entendido',
            onPress: () => {
              setHasSharedBefore(true);
              doShare();
            },
          },
        ]
      );
      return;
    }
    doShare();
  };

  const doShare = async () => {
    const shareText = `Este es mi Confío address para recibir dinero digital: ${addressUrl}

⚠️ Solo para envíos personales. Los pagos a negocios se deben hacer por la función "Pagar" en la app de Confío.`;

    try {
      await Share.share({
        message: shareText,
        title: 'Mi dirección de Confío',
      });
    } catch (error) {
      console.error('Error sharing:', error);
    }
  };

  const handleCopyAddress = () => {
    Clipboard.setString(addressUrl);
    Alert.alert('Dirección copiada');
  };

  const handleSaveQR = async () => {
    try {
      const qrNode = qrRef.current;
      if (!qrNode) {
        throw new Error('QR code reference not found');
      }
      if (typeof qrNode.capture !== 'function') {
        throw new Error('QR code capture method not found');
      }
      const uri = await qrNode.capture();
      await CameraRoll.save(uri, { type: 'photo' });
      Alert.alert('Éxito', 'QR guardado en galería');
    } catch (error) {
      console.error('Error saving QR:', error);
      Alert.alert('Error', 'No se pudo guardar el QR. Por favor, intenta de nuevo.');
    }
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Mi dirección de Confío"
        backgroundColor={colors.primary}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.content}>
        <ViewShot ref={qrRef} options={{ format: 'png', quality: 1 }}>
          <View style={{ alignItems: 'center', marginBottom: 16 }}>
            <Image
              source={require('../assets/png/CONFIO.png')}
              style={{ width: 64, height: 64, resizeMode: 'contain', marginBottom: 4 }}
            />
            <Text style={{ color: '#00b894', fontWeight: 'bold', fontSize: 16 }}>confio.lat</Text>
          </View>
          <View style={styles.addressSection}>
            <Text style={styles.addressLabel}>Tu dirección personal</Text>
            <View style={styles.addressDisplay}>
              <Text style={styles.addressText}>{username}</Text>
              <TouchableOpacity style={styles.copyBtn} onPress={handleCopyAddress}>
                <Text style={styles.copyBtnText}>Copiar</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.infoSection}>
              <Text style={styles.infoText}>
                {'✅ Esta es tu dirección personal para recibir dinero\n✅ Envíos entre personas = gratis\n✅ Funciona desde cualquier navegador'}
              </Text>
            </View>
          </View>

          <View style={styles.qrSection}>
            <View style={styles.qrCode}>
              <View style={styles.qrCodeInner}>
                <QRCode
                  value={addressUrl}
                  size={170}
                  color={colors.primary}
                  backgroundColor={colors.white}
                />
              </View>
            </View>
            <View style={styles.actions}>
              <TouchableOpacity style={styles.btnPrimary} onPress={handleShare}>
                <Icon name="share-2" size={20} color={colors.white} />
                <Text style={styles.btnPrimaryText}>Compartir</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.btnSecondary} onPress={handleSaveQR}>
                <Icon name="download" size={20} color={colors.text} />
                <Text style={styles.btnSecondaryText}>Guardar QR</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ViewShot>

        <View style={styles.warning}>
          <View style={styles.warningHeader}>
            <Icon name="alert-triangle" size={20} color={colors.warningText} />
            <Text style={styles.warningTitle}>Importante - Solo uso personal</Text>
          </View>
          <Text style={styles.warningText}>
            Esta dirección es para recibir fondos personales. Si eres comercio o negocio, debes usar el botón "Pagar" en la app (comisión 0.9% para soporte y facturación).
          </Text>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollView: {
    flex: 1,
  },
  content: {
    padding: 20,
  },
  qrSection: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    marginBottom: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  qrCode: {
    width: 200,
    height: 200,
    backgroundColor: colors.white,
    borderRadius: 12,
    marginBottom: 20,
    alignSelf: 'center',
    padding: 0,
    borderWidth: 2,
    borderColor: colors.primary,
    borderStyle: 'dashed',
    justifyContent: 'center',
    alignItems: 'center',
  },
  qrCodeInner: {
    width: 170,
    height: 170,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 8,
  },
  actions: {
    flexDirection: 'row',
    gap: 12,
  },
  btnPrimary: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  btnPrimaryText: {
    color: colors.white,
    fontSize: 16,
    fontWeight: '600',
  },
  btnSecondary: {
    flex: 1,
    backgroundColor: colors.background,
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  btnSecondaryText: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  addressSection: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    marginBottom: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  addressLabel: {
    fontSize: 14,
    color: colors.textLight,
    marginBottom: 8,
    fontWeight: '500',
  },
  addressDisplay: {
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
    marginBottom: 8,
  },
  addressText: {
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 16,
    color: colors.text,
  },
  copyBtn: {
    marginLeft: 16,
    backgroundColor: colors.primary,
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 14,
  },
  copyBtnText: {
    color: colors.white,
    fontWeight: 'bold',
    fontSize: 14,
  },
  infoSection: {
    backgroundColor: colors.info,
    borderRadius: 12,
    padding: 16,
  },
  infoText: {
    fontSize: 13,
    color: colors.infoText,
    lineHeight: 20,
  },
  warning: {
    backgroundColor: colors.warning,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: 12,
    padding: 16,
  },
  warningHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.warningText,
  },
  warningText: {
    fontSize: 13,
    color: colors.warningText,
    lineHeight: 20,
  },
}); 