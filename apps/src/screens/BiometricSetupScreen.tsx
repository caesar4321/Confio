import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';

// Route name retained for existing phone-verification and login navigation.
export const BiometricSetupScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<AuthStackParamList>>();
  const { completeBiometricAndEnter } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const enter = async () => {
    if (busy) return;
    setBusy(true);
    try { setFailed(!(await completeBiometricAndEnter())); }
    finally { setBusy(false); }
  };
  return <View style={styles.container}>
    <Text style={styles.title}>Confío Face</Text>
    <Text style={styles.body}>Si ya verificaste tu identidad, confirma con tu rostro que eres tú para abrir Confío. Cada envío requiere su propia aprobación.</Text>
    {failed && <Text accessibilityRole="alert" style={styles.body}>No pudimos confirmar tu identidad. Revisa tu conexión y vuelve a intentar.</Text>}
    <Pressable accessibilityRole="button" disabled={busy} onPress={enter} style={styles.button}>
      {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.label}>Continuar</Text>}
    </Pressable>
    <Pressable accessibilityRole="button" onPress={() => navigation.navigate('EmergencyExit')}>
      <Text style={styles.body}>Salida de emergencia</Text>
    </Pressable>
  </View>;
};
const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: 28, backgroundColor: '#fff' },
  title: { fontSize: 28, fontWeight: '700', color: '#111827', marginBottom: 20 },
  body: { fontSize: 16, color: '#4B5563', marginVertical: 16, lineHeight: 24 },
  button: { backgroundColor: '#10B981', padding: 18, borderRadius: 12, alignItems: 'center' },
  label: { color: '#fff', fontSize: 17, fontWeight: '600' },
});
export default BiometricSetupScreen;
