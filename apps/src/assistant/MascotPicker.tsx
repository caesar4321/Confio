// Pick the pet Confio Assistant wears: create your own (from an idea or a photo of
// your pet, like dots/Muse), or a built-in one with your color. Plus a name.
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Image, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { pickFromLibrary } from '../services/systemPicker';
import Icon from 'react-native-vector-icons/Feather';
import { Text, TextInput } from '../components/common/AppText';
import {
  CREATE_ASSISTANT_PET,
  DELETE_ASSISTANT_PET,
  GET_ASSISTANT_PETS,
  UPDATE_ASSISTANT_PROFILE,
  USE_ASSISTANT_PET,
  type AssistantPet,
  type AssistantProfile,
} from './api';
import { useAssistant } from './AssistantContext';
import AssistantMascot, { MASCOTS, MASCOT_COLORS, defaultMascotColor, type MascotKind } from './AssistantMascot';

const EMERALD = '#047857';

type Props = {
  visible: boolean;
  profile: AssistantProfile | null;
  onClose: () => void;
  onSaved: (profile: AssistantProfile) => void;
};

export default function MascotPicker({ visible, profile, onClose, onSaved }: Props) {
  const [kind, setKind] = useState<MascotKind>('CONFI');
  const [color, setColor] = useState('');
  const [name, setName] = useState('');
  const [wakeWord, setWakeWord] = useState(false);
  const { plan } = useAssistant();
  const [error, setError] = useState<string | null>(null);
  // Refetch every live thread query (bubble, sheet, wake-word listener) so a
  // changed setting, like turning the wake word off, applies everywhere.
  const [save, { loading }] = useMutation(UPDATE_ASSISTANT_PROFILE, { refetchQueries: ['GetAssistantThread'] });
  const [usePet] = useMutation(USE_ASSISTANT_PET, { refetchQueries: ['GetAssistantThread'] });
  const [createPet] = useMutation(CREATE_ASSISTANT_PET);
  const [deletePet] = useMutation(DELETE_ASSISTANT_PET);
  const { data: petsData, refetch: refetchPets } = useQuery(GET_ASSISTANT_PETS, {
    skip: !visible,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  const myPets: AssistantPet[] = petsData?.assistantPets ?? [];
  // A created pet being worn (or picked), else null for a built-in one.
  const [petId, setPetId] = useState<string | null>(null);
  const [idea, setIdea] = useState('');
  const [creating, setCreating] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const selectedPet = myPets.find((p) => p.id === petId) ?? null;

  // Drafts start from the profile when the picker OPENS; later refreshes
  // (polling, a new signed image URL) must not wipe what the user is editing.
  const wasVisible = useRef(false);
  useEffect(() => {
    const opened = visible && !wasVisible.current;
    wasVisible.current = visible;
    if (opened) {
      setKind(((profile?.mascot as MascotKind) || 'CONFI'));
      setColor(profile?.mascotColor || '');
      setName(profile?.mascotName || '');
      setWakeWord(!!profile?.wakeWordEnabled);
      setPetId(profile?.mascot === 'CUSTOM' ? profile?.customPetId ?? null : null);
      setLeft(profile?.petCreationsLeft ?? null);
      setIdea('');
      setError(null);
    }
  }, [visible, profile]);

  const shownColor = color || defaultMascotColor(kind);

  const create = async (fromPhoto: boolean) => {
    setError(null);
    let photo: { base64: string; type: string } | null = null;
    if (fromPhoto) {
      const picked = await pickFromLibrary({
        mediaType: 'photo',
        selectionLimit: 1,
        includeBase64: true,
        maxWidth: 1024,
        maxHeight: 1024,
        quality: 0.8,
      });
      const asset = picked.assets?.[0];
      if (!asset?.base64) {
        return;
      }
      photo = { base64: asset.base64, type: asset.type || 'image/jpeg' };
    } else if (idea.trim().length < 3) {
      setError('Cuéntanos cómo quieres a tu asistente.');
      return;
    }
    setCreating(true);
    try {
      const { data } = await createPet({
        variables: {
          idea: idea.trim() || null,
          photoBase64: photo?.base64 ?? null,
          photoMimeType: photo?.type ?? null,
        },
      });
      const result = data?.createAssistantPet;
      if (typeof result?.creationsLeft === 'number') {
        setLeft(result.creationsLeft);
      }
      if (!result?.success || !result.pet) {
        setError(result?.error || 'No pudimos crear tu asistente.');
        return;
      }
      await refetchPets();
      setPetId(result.pet.id);
      setIdea('');
    } catch {
      setError('No pudimos crear tu asistente. Inténtalo de nuevo.');
    } finally {
      setCreating(false);
    }
  };

  const removePet = (pet: AssistantPet) => {
    Alert.alert('¿Borrar este personaje?', undefined, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Borrar',
        style: 'destructive',
        onPress: async () => {
          await deletePet({ variables: { petId: pet.id } }).catch(() => {});
          if (petId === pet.id) {
            setPetId(null);
          }
          void refetchPets();
        },
      },
    ]);
  };

  const submit = async () => {
    try {
      if (petId) {
        const worn = await usePet({ variables: { petId } });
        if (!worn.data?.useAssistantPet?.success) {
          setError(worn.data?.useAssistantPet?.error || 'No pude usar ese personaje.');
          return;
        }
      }
      const { data } = await save({
        variables: {
          ...(petId ? {} : { mascot: kind, mascotColor: color }),
          mascotName: name.trim(),
          ...(plan?.wakeWordAvailable ? { wakeWordEnabled: wakeWord } : {}),
        },
      });
      const next = data?.updateAssistantProfile?.profile;
      if (next) {
        onSaved(next);
      }
      onClose();
    } catch {
      setError('No pude guardar. Inténtalo de nuevo.');
    }
  };

  return (
    <Modal visible={visible} animationType="fade" transparent onRequestClose={onClose}>
      <View style={styles.scrim}>
        <View style={styles.card}>
          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            <View style={styles.preview}>
              {creating ? (
                <View style={styles.creating}>
                  <ActivityIndicator color={EMERALD} />
                  <Text style={styles.creatingText}>Dibujando a tu asistente…</Text>
                </View>
              ) : selectedPet ? (
                <AssistantMascot kind="CUSTOM" imageUrl={selectedPet.imageUrl} size={96} mood="happy" />
              ) : (
                <AssistantMascot kind={kind} color={shownColor} size={96} mood="happy" />
              )}
              <Text style={styles.previewName}>
                {name.trim() || (selectedPet ? 'Tu asistente' : MASCOTS.find((m) => m.kind === kind)?.label)}
              </Text>
            </View>

            <Text style={styles.label}>Personaliza a tu asistente</Text>
            <TextInput
              style={styles.input}
              value={idea}
              onChangeText={setIdea}
              placeholder="Ej: una llama con poncho y lentes de sol"
              placeholderTextColor="#9CA3AF"
              maxLength={300}
              editable={!creating}
            />
            <View style={styles.createRow}>
              <Pressable
                style={[styles.createButton, (creating || left === 0) && styles.disabled]}
                onPress={() => create(false)}
                disabled={creating || left === 0}
              >
                <Icon name="feather" size={16} color="#FFFFFF" />
                <Text style={styles.createText}>Crear</Text>
              </Pressable>
              <Pressable
                style={[styles.photoButton, (creating || left === 0) && styles.disabled]}
                onPress={() => create(true)}
                disabled={creating || left === 0}
              >
                <Icon name="image" size={16} color={EMERALD} />
                <Text style={styles.photoText}>Desde una foto de tu mascota</Text>
              </Pressable>
            </View>
            {left !== null ? (
              <Text style={styles.hint}>
                {left === 0
                  ? profile?.petCreationsPeriod === 'day'
                    ? 'Ya creaste tus personajes de hoy.'
                    : plan?.plusSalesEnabled
                      ? 'Ya creaste tus personajes de esta semana. Con Assistant+ puedes crear más.'
                      : 'Ya creaste tus personajes de esta semana. La próxima semana puedes crear más.'
                  : `Te quedan ${left} ${profile?.petCreationsPeriod === 'day' ? 'hoy' : 'esta semana'}.`}
              </Text>
            ) : null}
            {myPets.length ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.petRow}>
                {myPets.map((pet) => (
                  <Pressable
                    key={pet.id}
                    onPress={() => setPetId(pet.id)}
                    onLongPress={() => removePet(pet)}
                    style={[styles.petOption, petId === pet.id && styles.optionSelected]}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: petId === pet.id }}
                    accessibilityLabel={pet.idea || 'Tu asistente'}
                    accessibilityHint="Mantén presionado para borrarla"
                  >
                    {pet.imageUrl ? <Image source={{ uri: pet.imageUrl }} style={styles.petImage} /> : null}
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}

            <Text style={styles.label}>Tu asistente</Text>
            <View style={styles.grid}>
              {MASCOTS.map((m) => (
                <Pressable
                  key={m.kind}
                  onPress={() => {
                    setKind(m.kind);
                    setColor('');
                    setPetId(null);
                  }}
                  style={[styles.option, !petId && kind === m.kind && styles.optionSelected]}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: kind === m.kind }}
                  accessibilityLabel={m.label}
                >
                  <AssistantMascot kind={m.kind} size={48} animated={false} />
                  <Text style={styles.optionText}>{m.label}</Text>
                </Pressable>
              ))}
            </View>

            {!petId ? <Text style={styles.label}>Color</Text> : null}
            <View style={[styles.colors, petId ? styles.hidden : null]}>
              {MASCOT_COLORS.map((c) => (
                <Pressable
                  key={c}
                  onPress={() => setColor(c)}
                  style={[styles.swatch, { backgroundColor: c }, shownColor === c && styles.swatchSelected]}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: shownColor === c }}
                  accessibilityLabel={`Color ${c}`}
                />
              ))}
            </View>

            <Text style={styles.label}>Nombre</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Ponle un nombre (opcional)"
              placeholderTextColor="#9CA3AF"
              maxLength={24}
            />

            {plan?.wakeWordAvailable ? (
              <Pressable
                style={styles.toggleRow}
                onPress={() => setWakeWord((on) => !on)}
                accessibilityRole="switch"
                accessibilityState={{ checked: wakeWord }}
              >
                <View style={[styles.checkbox, wakeWord && styles.checkboxOn]} />
                <Text style={styles.toggleText}>
                  Di “Confío” para dejar una nota de voz. Solo con la app abierta: verás el indicador del micrófono, y
                  el audio no sale del teléfono hasta que te escuche decirlo.
                </Text>
              </Pressable>
            ) : null}
            <Text style={styles.tip}>Arrastra la burbuja a cualquier lado si te tapa algo.</Text>

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <View style={styles.actions}>
              <Pressable onPress={onClose} style={[styles.button, styles.secondary]}>
                <Text style={styles.secondaryText}>Cancelar</Text>
              </Pressable>
              <Pressable onPress={submit} style={[styles.button, styles.primary]} disabled={loading}>
                <Text style={styles.primaryText}>{loading ? 'Guardando…' : 'Guardar'}</Text>
              </Pressable>
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: 'rgba(17,24,39,0.45)', justifyContent: 'center', padding: 16 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 24, maxHeight: '90%' },
  content: { padding: 20 },
  preview: { alignItems: 'center', marginBottom: 8 },
  previewName: { fontSize: 18, fontWeight: '700', color: '#111827', marginTop: 6 },
  label: { fontSize: 13, fontWeight: '600', color: '#6B7280', marginTop: 16, marginBottom: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: {
    width: 72,
    alignItems: 'center',
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: 'transparent',
    backgroundColor: '#F9FAFB',
  },
  optionSelected: { borderColor: EMERALD, backgroundColor: '#ECFDF5' },
  optionText: { fontSize: 12, color: '#374151', marginTop: 2 },
  colors: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  swatch: { width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: '#FFFFFF' },
  swatchSelected: { borderColor: '#111827' },
  input: {
    height: 44,
    borderRadius: 12,
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 14,
    fontSize: 15,
    color: '#111827',
  },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16 },
  checkbox: { width: 20, height: 20, borderRadius: 6, borderWidth: 2, borderColor: '#9CA3AF' },
  checkboxOn: { backgroundColor: EMERALD, borderColor: EMERALD },
  toggleText: { fontSize: 14, color: '#374151', flex: 1 },
  error: { color: '#B91C1C', fontSize: 13, marginTop: 10 },
  creating: { width: 96, height: 96, alignItems: 'center', justifyContent: 'center', gap: 6 },
  creatingText: { fontSize: 11, color: '#6B7280', textAlign: 'center' },
  createRow: { flexDirection: 'row', gap: 8, marginTop: 8, flexWrap: 'wrap' },
  createButton: {
    flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: EMERALD,
    borderRadius: 12, paddingHorizontal: 14, height: 40,
  },
  createText: { color: '#FFFFFF', fontWeight: '700', fontSize: 14 },
  photoButton: {
    flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: '#A7F3D0',
    backgroundColor: '#ECFDF5', borderRadius: 12, paddingHorizontal: 12, height: 40,
  },
  photoText: { color: EMERALD, fontWeight: '600', fontSize: 13 },
  disabled: { opacity: 0.45 },
  hidden: { display: 'none' },
  hint: { fontSize: 12, color: '#6B7280', marginTop: 6 },
  petRow: { gap: 8, paddingTop: 10 },
  petOption: { width: 64, height: 64, borderRadius: 32, borderWidth: 2, borderColor: 'transparent', overflow: 'hidden' },
  petImage: { width: '100%', height: '100%' },
  tip: { fontSize: 13, color: '#6B7280', marginTop: 14 },
  actions: { flexDirection: 'row', gap: 10, marginTop: 20 },
  button: { flex: 1, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  primary: { backgroundColor: EMERALD },
  primaryText: { color: '#FFFFFF', fontWeight: '700', fontSize: 15 },
  secondary: { backgroundColor: '#F3F4F6' },
  secondaryText: { color: '#374151', fontWeight: '600', fontSize: 15 },
});
