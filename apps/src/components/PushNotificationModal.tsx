import React, { useEffect, useRef } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  Dimensions,
  Animated,
  Platform,
  ScrollView,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { LinearGradient, Defs, Stop, Rect } from 'react-native-svg';

const { width, height } = Dimensions.get('window');

const colors = {
  primary: '#34D399',
  primaryDark: '#059669',
  primaryLight: '#D1FAE5',
  secondary: '#8B5CF6',
  dark: '#111827',
  gray: '#6B7280',
  lightGray: '#F3F4F6',
};

interface PushNotificationModalProps {
  visible: boolean;
  onAllow: () => void;
  onDeny: () => void;
  needsSettings?: boolean;
}

export const PushNotificationModal: React.FC<PushNotificationModalProps> = ({
  visible,
  onAllow,
  onDeny,
  needsSettings = false,
}) => {
  console.log('[PushNotificationModal] Component rendered with visible:', visible);
  const slideAnim = useRef(new Animated.Value(height)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (visible) {
      // Animate modal sliding up
      Animated.parallel([
        Animated.timing(slideAnim, {
          toValue: 0,
          duration: 300,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 300,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      // Animate modal sliding down
      Animated.parallel([
        Animated.timing(slideAnim, {
          toValue: height,
          duration: 300,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 300,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [visible, slideAnim, fadeAnim]);

  return (
    <Modal
      transparent
      visible={visible}
      animationType="none"
      statusBarTranslucent
    >
      <Animated.View 
        style={[
          styles.overlay,
          {
            opacity: fadeAnim,
          },
        ]}
      >
        <TouchableOpacity 
          style={StyleSheet.absoluteFillObject}
          activeOpacity={1}
          onPress={onDeny}
        />
        
        <Animated.View
          style={[
            styles.modalContent,
            {
              transform: [{ translateY: slideAnim }],
            },
          ]}
        >
          <ScrollView 
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.scrollContent}
          >
            {/* Header with gradient background */}
            <View style={styles.header}>
              <Svg height="200" width={width} style={StyleSheet.absoluteFillObject}>
                <Defs>
                  <LinearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <Stop offset="0%" stopColor={colors.primary} stopOpacity="0.1" />
                    <Stop offset="100%" stopColor={colors.secondary} stopOpacity="0.1" />
                  </LinearGradient>
                </Defs>
                <Rect x="0" y="0" width={width} height="200" fill="url(#grad)" />
              </Svg>
              
              <View style={styles.iconContainer}>
                <View style={styles.iconBackground}>
                  <Icon name="bell" size={48} color={colors.primary} />
                </View>
              </View>
            </View>

            {/* Content */}
            <View style={styles.content}>
              <Text style={styles.title}>
                {needsSettings ? 'Activa las notificaciones' : 'Mantente informado'}
              </Text>
              <Text style={styles.subtitle}>
                {needsSettings 
                  ? 'Para recibir alertas importantes, ve a Configuración y activa las notificaciones para Confío'
                  : 'Recibe notificaciones importantes sobre tus transacciones'}
              </Text>

              {/* Features */}
              <View style={styles.featuresContainer}>
                <View style={styles.feature}>
                  <View style={styles.featureIcon}>
                    <Icon name="zap" size={20} color={colors.primary} />
                  </View>
                  <View style={styles.featureText}>
                    <Text style={styles.featureTitle}>Alertas instantáneas</Text>
                    <Text style={styles.featureDescription}>
                      Recibe confirmación inmediata cuando alguien te envía dinero
                    </Text>
                  </View>
                </View>

                <View style={styles.feature}>
                  <View style={styles.featureIcon}>
                    <Icon name="shield" size={20} color={colors.primary} />
                  </View>
                  <View style={styles.featureText}>
                    <Text style={styles.featureTitle}>Seguridad mejorada</Text>
                    <Text style={styles.featureDescription}>
                      Mantente alerta sobre cualquier actividad en tu cuenta
                    </Text>
                  </View>
                </View>

                <View style={styles.feature}>
                  <View style={styles.featureIcon}>
                    <Icon name="trending-up" size={20} color={colors.primary} />
                  </View>
                  <View style={styles.featureText}>
                    <Text style={styles.featureTitle}>Ofertas exclusivas</Text>
                    <Text style={styles.featureDescription}>
                      Sé el primero en conocer promociones y nuevas funciones
                    </Text>
                  </View>
                </View>
              </View>

              {/* Privacy note */}
              <View style={styles.privacyContainer}>
                <Icon name="lock" size={16} color={colors.gray} />
                <Text style={styles.privacyText}>
                  Respetamos tu privacidad. Puedes cambiar tus preferencias en cualquier momento.
                </Text>
              </View>

              {/* Action buttons */}
              <View style={styles.buttonsContainer}>
                <TouchableOpacity
                  style={styles.allowButton}
                  onPress={onAllow}
                  activeOpacity={0.8}
                >
                  <Text style={styles.allowButtonText}>
                    {needsSettings ? 'Ir a configuración' : 'Permitir notificaciones'}
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={styles.denyButton}
                  onPress={onDeny}
                  activeOpacity={0.8}
                >
                  <Text style={styles.denyButtonText}>Ahora no</Text>
                </TouchableOpacity>
              </View>
            </View>
          </ScrollView>
        </Animated.View>
      </Animated.View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: height * 0.9,
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    height: 200,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  iconContainer: {
    marginTop: 40,
  },
  iconBackground: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.1,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 10,
  },
  content: {
    padding: 24,
    paddingTop: 16,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: colors.gray,
    textAlign: 'center',
    marginBottom: 32,
    lineHeight: 24,
  },
  featuresContainer: {
    marginBottom: 24,
  },
  feature: {
    flexDirection: 'row',
    marginBottom: 20,
  },
  featureIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  featureText: {
    flex: 1,
  },
  featureTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 4,
  },
  featureDescription: {
    fontSize: 14,
    color: colors.gray,
    lineHeight: 20,
  },
  privacyContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.lightGray,
    padding: 16,
    borderRadius: 12,
    marginBottom: 24,
  },
  privacyText: {
    flex: 1,
    fontSize: 13,
    color: colors.gray,
    marginLeft: 12,
    lineHeight: 18,
  },
  buttonsContainer: {
    gap: 12,
  },
  allowButton: {
    backgroundColor: colors.primary,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    shadowColor: colors.primary,
    shadowOpacity: 0.3,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 5,
  },
  allowButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  denyButton: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  denyButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.gray,
  },
});