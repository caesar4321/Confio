import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { TeamBadge } from '../components/TeamBadge';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { CREATE_TEAM, UPDATE_TEAM } from '../apollo/mutations';
import { GET_TEAM } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { TEAM_COLORS, TEAM_DESCRIPTION_MAX, TEAM_EMOJIS, TEAM_NAME_MAX, TEAM_NAME_MIN, Team } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'TeamEdit'>['route'];

/** Crear / editar equipo. The name and description are reviewed by the server. */
export const TeamEditScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const teamId = route.params?.teamId;
  const client = useApolloClient();
  const [loaded, setLoaded] = useState(!teamId);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [emoji, setEmoji] = useState(TEAM_EMOJIS[0]);
  const [color, setColor] = useState(TEAM_COLORS[0]);
  const [joinMode, setJoinMode] = useState<'open' | 'approval'>('open');
  const [createTeam, { loading: creating }] = useMutation(CREATE_TEAM);
  const [updateTeam, { loading: updating }] = useMutation(UPDATE_TEAM);
  const saving = creating || updating;

  useEffect(() => {
    if (!teamId) return;
    client.query({ query: GET_TEAM, variables: { teamId }, fetchPolicy: 'network-only' })
      .then(({ data }) => {
        const team = data?.team as Team | null;
        if (!team?.isCaptain) {
          navigation.goBack();
          return;
        }
        setName(team.name);
        setDescription(team.description);
        setEmoji(team.emoji);
        setColor(team.color);
        setJoinMode(team.joinMode === 'approval' ? 'approval' : 'open');
        setLoaded(true);
      })
      .catch(() => navigation.goBack());
  }, [client, navigation, teamId]);

  const trimmed = name.trim();
  const valid = trimmed.length >= TEAM_NAME_MIN && trimmed.length <= TEAM_NAME_MAX;

  const save = async () => {
    if (!valid || saving) return;
    const variables = { name: trimmed, description: description.trim(), emoji, color, joinMode };
    try {
      if (teamId) {
        const { data } = await updateTeam({ variables: { teamId, ...variables } });
        const result = data?.updateTeam;
        if (!result?.success) {
          Alert.alert('No pudimos guardar el equipo', result?.error || 'Inténtalo de nuevo.');
          return;
        }
        navigation.goBack();
      } else {
        const { data } = await createTeam({ variables });
        const result = data?.createTeam;
        if (!result?.success || !result.team?.id) {
          Alert.alert('No pudimos crear el equipo', result?.error || 'Inténtalo de nuevo.');
          return;
        }
        navigation.replace('Team', { teamId: result.team.id });
      }
    } catch {
      Alert.alert('No pudimos guardar el equipo', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  return (
    <View style={styles.container}>
      <Header title={teamId ? 'Editar equipo' : 'Crear equipo'} navigation={navigation as any}
        onBackPress={() => navigation.goBack()} backgroundColor={colors.background} isLight={false} />
      {!loaded ? (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      ) : (
        <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            <View style={styles.preview}>
              <TeamBadge emoji={emoji} color={color} size={80} />
              <Text style={styles.previewName} numberOfLines={1}>{trimmed || 'Tu equipo'}</Text>
            </View>

            <Text style={styles.label}>Nombre</Text>
            <TextInput value={name} onChangeText={setName} maxLength={TEAM_NAME_MAX} style={styles.input}
              placeholder="Ej: Los Alcistas" placeholderTextColor={colors.textSecondary} />
            <Text style={styles.hint}>De {TEAM_NAME_MIN} a {TEAM_NAME_MAX} caracteres. Sin datos de contacto ni redes.</Text>

            <Text style={styles.label}>Descripción (opcional)</Text>
            <TextInput value={description} onChangeText={setDescription} maxLength={TEAM_DESCRIPTION_MAX} multiline
              style={[styles.input, styles.multiline]} placeholder="¿Cómo invierte tu equipo?" placeholderTextColor={colors.textSecondary} />

            <Text style={styles.label}>Emoji</Text>
            <View style={styles.grid}>
              {TEAM_EMOJIS.map((e) => (
                <Pressable key={e} onPress={() => setEmoji(e)} style={[styles.emoji, e === emoji && styles.selected]}
                  accessibilityRole="button" accessibilityState={{ selected: e === emoji }}>
                  <Text style={styles.emojiText} allowFontScaling={false}>{e}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.label}>Color</Text>
            <View style={styles.grid}>
              {TEAM_COLORS.map((c) => (
                <Pressable key={c} onPress={() => setColor(c)} accessibilityRole="button" accessibilityState={{ selected: c === color }}
                  style={[styles.swatch, { backgroundColor: c }, c === color && styles.swatchSelected]} />
              ))}
            </View>

            <Text style={styles.label}>¿Quién puede entrar?</Text>
            {(['open', 'approval'] as const).map((mode) => (
              <Pressable key={mode} onPress={() => setJoinMode(mode)} style={[styles.option, joinMode === mode && styles.selected]}
                accessibilityRole="radio" accessibilityState={{ selected: joinMode === mode }}>
                <Text style={styles.optionTitle}>{mode === 'open' ? 'Abierto' : 'Con aprobación'}</Text>
                <Text style={styles.hint}>
                  {mode === 'open' ? 'Cualquier inversor verificado entra directo.' : 'Tú apruebas cada solicitud.'}
                </Text>
              </Pressable>
            ))}

            <Pressable style={[styles.save, (!valid || saving) && styles.disabled]} disabled={!valid || saving}
              onPress={() => { void save(); }} accessibilityRole="button">
              {saving ? <ActivityIndicator color={colors.white} /> : (
                <Text style={styles.saveText}>{teamId ? 'Guardar' : 'Crear equipo'}</Text>
              )}
            </Pressable>
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </View>
  );
};

export default TeamEditScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  loading: { marginTop: 32 },
  content: { padding: 16, paddingBottom: 40 },
  preview: { alignItems: 'center', gap: 8, marginBottom: 8 },
  previewName: { fontSize: 18, fontWeight: '700', color: colors.dark },
  label: { marginTop: 18, marginBottom: 6, fontSize: 14, fontWeight: '600', color: colors.dark },
  hint: { marginTop: 4, fontSize: 12, color: colors.textSecondary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: colors.dark },
  multiline: { minHeight: 72, textAlignVertical: 'top' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  emoji: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
  emojiText: { fontSize: 22 },
  selected: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  swatch: { width: 36, height: 36, borderRadius: 18 },
  swatchSelected: { borderWidth: 3, borderColor: colors.dark },
  option: { padding: 12, marginBottom: 8, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  optionTitle: { fontSize: 15, fontWeight: '600', color: colors.dark },
  save: { marginTop: 24, paddingVertical: 14, borderRadius: 24, alignItems: 'center', backgroundColor: colors.primaryDark },
  saveText: { fontSize: 16, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.5 },
});
