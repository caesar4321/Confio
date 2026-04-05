import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { UPDATE_USERNAME } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { colors } from '../config/theme';

const normalizeChunk = (value: string) => {
  if (!value) return 'confio';
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
    .slice(0, 12) || 'confio';
};

export const UpdateUsernameScreen: React.FC = () => {
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { userProfile, refreshProfile } = useAuth();
  const currentUsername = userProfile?.username || '';
  const [username, setUsername] = useState(currentUsername);
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [updateUsername] = useMutation(UPDATE_USERNAME);

  const validateUsername = (value: string) => {
    const trimmed = value.trim();
    if (trimmed.length < 3) {
      return 'El usuario debe tener al menos 3 caracteres';
    }
    if (trimmed.length > 30) {
      return 'El usuario no puede tener más de 30 caracteres';
    }
    if (!/^[a-zA-Z0-9_]+$/.test(trimmed)) {
      return 'Solo se permiten letras, números y guiones bajos (_)';
    }
    return null;
  };

  const sanitizedFirst = useMemo(() => normalizeChunk(userProfile?.firstName || ''), [userProfile?.firstName]);
  const sanitizedLast = useMemo(() => normalizeChunk(userProfile?.lastName || ''), [userProfile?.lastName]);
  const phoneSuffix = useMemo(() => {
    const digits = (userProfile?.phoneNumber || '').replace(/\D/g, '');
    return digits.slice(-4);
  }, [userProfile?.phoneNumber]);

  const suggestions = useMemo(() => {
    const baseCandidates = new Set<string>();

    if (currentUsername && !currentUsername.startsWith('user_') && !/^[a-z0-9]{10,}$/.test(currentUsername)) {
      baseCandidates.add(normalizeChunk(currentUsername));
    }

    if (sanitizedFirst) {
      baseCandidates.add(sanitizedFirst);
      if (sanitizedLast) {
        baseCandidates.add(`${sanitizedFirst}${sanitizedLast.charAt(0)}`);
        baseCandidates.add(`${sanitizedFirst}_${sanitizedLast}`);
      }
      baseCandidates.add(`${sanitizedFirst}confio`);
      baseCandidates.add(`${sanitizedFirst}ve`);
      if (phoneSuffix.length >= 2) {
        baseCandidates.add(`${sanitizedFirst}${phoneSuffix}`);
      }
    }

    if (sanitizedLast) {
      baseCandidates.add(`${sanitizedLast}${sanitizedFirst.charAt(0)}`);
    }

    const fallback = normalizeChunk('confio');
    baseCandidates.add(fallback);
    baseCandidates.add(`${fallback}${new Date().getFullYear()}`);

    const unique = Array.from(baseCandidates)
      .map((candidate) => candidate.slice(0, 24))
      .filter((candidate) => candidate.length >= 3)
      .filter((candidate) => candidate !== currentUsername);

    return unique.slice(0, 6);
  }, [currentUsername, sanitizedFirst, sanitizedLast]);

  const handleSuggestionPress = (suggestion: string) => {
    setUsername(suggestion);
    setUsernameError(null);
  };

  const handleSave = async () => {
    const trimmed = username.trim();
    const validation = validateUsername(trimmed);
    if (validation) {
      setUsernameError(validation);
      return;
    }
    if (trimmed === currentUsername) {
      Alert.alert('Sin cambios', 'Tu usuario ya está configurado con ese nombre.');
      return;
    }

    setIsSaving(true);
    setUsernameError(null);
    try {
      const { data } = await updateUsername({
        variables: { username: trimmed },
      });
      if (data?.updateUsername?.success) {
        await refreshProfile('personal');
        Alert.alert('Listo', 'Tu usuario se actualizó correctamente.', [
          { text: 'Entendido', onPress: () => navigation.goBack() },
        ]);
      } else {
        const message = data?.updateUsername?.error || 'No se pudo actualizar el usuario. Intenta con otro nombre.';
        setUsernameError(message);
      }
    } catch (error) {
      setUsernameError('No se pudo actualizar el usuario. Inténtalo nuevamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const helperMessage = useMemo(() => {
    if (!currentUsername) {
      return 'Crea un usuario único y fácil de recordar para tus invitaciones.';
    }
    if (currentUsername.startsWith('user_') || /^[a-z0-9]{10,}$/.test(currentUsername)) {
      return 'Tu usuario actual fue creado automáticamente. Te recomendamos elegir uno más sencillo.';
    }
    return 'Puedes actualizar tu usuario en cualquier momento para hacerlo más fácil de compartir.';
  }, [currentUsername]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={20} color={colors.white} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Actualizar usuario</Text>
        <TouchableOpacity
          style={[styles.headerButton, styles.saveButton, isSaving && styles.saveButtonDisabled]}
          onPress={handleSave}
          disabled={isSaving}
        >
          <Text style={styles.saveButtonText}>{isSaving ? 'Guardando…' : 'Guardar'}</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.container} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.infoCard}>
          <Text style={styles.infoTitle}>Tu usuario Confío</Text>
          <Text style={styles.infoDescription}>
            Comparte este usuario para que tus amigos lo escriban cuando Confío pregunte "¿Quién te invitó?". Mientras
            más fácil de recordar, más invitaciones exitosas tendrás.
          </Text>
          <View style={styles.currentUsernameBox}>
            <Text style={styles.currentLabel}>Usuario actual</Text>
            <Text style={styles.currentValue}>{currentUsername ? `@${currentUsername}` : 'Sin configurar'}</Text>
          </View>
          <Text style={styles.helperText}>{helperMessage}</Text>
        </View>

        <View style={styles.inputCard}>
          <Text style={styles.inputLabel}>Nuevo usuario</Text>
          <View style={[styles.inputRow, usernameError && styles.inputRowError]}>
            <Text style={styles.inputPrefix}>@</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={(text) => {
                setUsername(text);
                setUsernameError(null);
              }}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="maria_confio"
              placeholderTextColor={colors.muted}
              maxLength={30}
            />
          </View>
          <View style={styles.inputFooter}>
            <Text style={styles.inputHint}>Letras, números y guiones bajos.</Text>
            <Text style={[styles.charCount, username.length > 25 && styles.charCountWarn]}>
              {username.length}/30
            </Text>
          </View>
          {usernameError && <Text style={styles.errorText}>{usernameError}</Text>}
        </View>

        {suggestions.length > 0 && (
          <View style={styles.suggestionsCard}>
            <Text style={styles.suggestionsTitle}>Sugerencias rápidas</Text>
            <View style={styles.suggestionsRow}>
              {suggestions.slice(0, 6).map((suggestion) => (
                <TouchableOpacity
                  key={suggestion}
                  style={styles.suggestionChip}
                  onPress={() => handleSuggestionPress(suggestion)}
                >
                  <Text style={styles.suggestionText}>@{suggestion}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}

        <View style={styles.tipsCard}>
          <Text style={styles.tipsTitle}>Consejos</Text>
          <Text style={styles.tipItem}>• Evita usuarios largos o difíciles de dictar.</Text>
          <Text style={styles.tipItem}>• Usa tu nombre, apodo o negocio para que te recuerden fácilmente.</Text>
          <Text style={styles.tipItem}>• El usuario se mostrará en tu perfil y en tus invitaciones.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.primaryDark,
  },
  headerButton: {
    padding: 8,
    borderRadius: 8,
  },
  headerTitle: {
    color: colors.white,
    fontSize: 18,
    fontWeight: '600',
  },
  saveButton: {
    backgroundColor: colors.white,
    paddingHorizontal: 14,
  },
  saveButtonDisabled: {
    opacity: 0.5,
  },
  saveButtonText: {
    color: colors.primaryDark,
    fontWeight: '700',
  },
  container: {
    flex: 1,
  },
  content: {
    padding: 20,
    gap: 16,
    paddingBottom: 32,
  },
  infoCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 12,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 2,
  },
  infoTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textFlat,
  },
  infoDescription: {
    fontSize: 14,
    color: colors.textSecondary,
    lineHeight: 20,
  },
  currentUsernameBox: {
    padding: 14,
    backgroundColor: colors.neutral,
    borderRadius: 12,
  },
  currentLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: 4,
  },
  currentValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textFlat,
  },
  helperText: {
    fontSize: 13,
    color: colors.primaryDark,
    lineHeight: 19,
  },
  inputCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 12,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 2,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textFlat,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderRadius: 12,
    backgroundColor: colors.white,
    paddingHorizontal: 14,
  },
  inputRowError: {
    borderColor: colors.danger,
  },
  inputPrefix: {
    fontSize: 17,
    fontWeight: '600',
    color: colors.primaryDark,
    marginRight: 4,
  },
  input: {
    flex: 1,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.textFlat,
  },
  inputFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  inputHint: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  charCount: {
    fontSize: 12,
    color: colors.muted,
  },
  charCountWarn: {
    color: colors.error.icon,
  },
  errorText: {
    fontSize: 13,
    color: colors.danger,
  },
  suggestionsCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 12,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 2,
  },
  suggestionsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textFlat,
  },
  suggestionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  suggestionChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
  },
  suggestionText: {
    color: colors.primaryDark,
    fontWeight: '600',
  },
  tipsCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 8,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 2,
  },
  tipsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textFlat,
  },
  tipItem: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 19,
  },
});

export default UpdateUsernameScreen;
