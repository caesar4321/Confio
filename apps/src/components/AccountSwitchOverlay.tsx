import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  ActivityIndicator,
  Dimensions,
} from 'react-native';
import { colors } from '../config/theme';

interface AccountSwitchOverlayProps {
  visible: boolean;
  progress: string;
}

const { height } = Dimensions.get('window');

export const AccountSwitchOverlay: React.FC<AccountSwitchOverlayProps> = ({
  visible,
  progress,
}) => {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
    >
      <View style={styles.overlay}>
        <View style={styles.container}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.title}>Cambiando cuenta...</Text>
          {progress ? (
            <Text style={styles.progress}>{progress}</Text>
          ) : null}
          <Text style={styles.warning}>
            Por favor no cierres la aplicación
          </Text>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  container: {
    backgroundColor: colors.background,
    borderRadius: 16,
    padding: 32,
    alignItems: 'center',
    width: '80%',
    maxWidth: 300,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
    elevation: 5,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text,
    marginTop: 16,
    marginBottom: 8,
  },
  progress: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 8,
    textAlign: 'center',
  },
  warning: {
    fontSize: 12,
    color: colors.textTertiary,
    marginTop: 16,
    textAlign: 'center',
  },
});