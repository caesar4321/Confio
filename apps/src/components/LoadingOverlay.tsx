import React from 'react';
import { Modal, View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors } from '../config/theme';

type LoadingOverlayProps = {
  visible: boolean;
  message?: string;
};

export const LoadingOverlay: React.FC<LoadingOverlayProps> = ({ visible, message }) => {
  const displayMessage = (message && message.trim().length > 0) ? message : 'Procesando…';
  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.container}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.title}>{displayMessage}</Text>
          <Text style={styles.hint}>Por favor no cierres la aplicación</Text>
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
    maxWidth: 320,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
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
    textAlign: 'center',
  },
  hint: {
    fontSize: 12,
    color: colors.textTertiary,
    marginTop: 6,
    textAlign: 'center',
  },
});

export default LoadingOverlay;
