// Stores where the assistant's browser keeps the person's sign-in
// (agentStores). Each can be forgotten: deleted at the browser vendor too.
import React, { useState } from 'react';
import { ActivityIndicator, Alert, FlatList, StatusBar, StyleSheet, View } from 'react-native';
import { NavigationProp, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { FORGET_AGENT_STORE, GET_AGENT_STORES } from './api';

type Navigation = NavigationProp<MainStackParamList>;

const FORGET_DEADLINE_MS = 30_000;

export const AgentStoresScreen: React.FC = () => {
  const navigation = useNavigation<Navigation>();
  const { data, loading, error, refetch } = useQuery(GET_AGENT_STORES, { fetchPolicy: 'network-only' });
  const [forget] = useMutation(FORGET_AGENT_STORE);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const stores: string[] = data?.agentStores ?? [];
  // The list is the personal account's: from any other account the server answers nothing.
  const otherAccount = !!data && data.agentStores == null;

  const onForget = (site: string) => {
    Alert.alert(
      'Cerrar sesión en esta tienda',
      `El asistente ya no tendrá tu sesión de ${site}. La próxima vez tendrás que iniciar sesión de nuevo.`,
      [
        { text: 'Volver', style: 'cancel' },
        {
          text: 'Cerrar sesión',
          style: 'destructive',
          onPress: async () => {
            setBusy(site);
            setMessage(null);
            // A request that never answers does not lock the list: the next read shows what happened.
            let expired = false;
            const deadline = setTimeout(() => {
              expired = true;
              setBusy(null);
              refetch().catch(() => undefined);
            }, FORGET_DEADLINE_MS);
            try {
              const result = await forget({ variables: { site } });
              if (expired) {
                refetch().catch(() => undefined);
                return;
              }
              const answer = result.data?.forgetAgentStore;
              setMessage(answer?.success
                ? { text: `Listo: se borró tu sesión de ${site}.`, ok: true }
                : { text: answer?.errors?.[0] || 'No pude borrarla. Inténtalo de nuevo.', ok: false });
              refetch().catch(() => undefined);  // a list that did not refresh does not undo the answer
            } catch {
              if (!expired) {
                setMessage({ text: 'No pude borrarla. Revisa tu conexión.', ok: false });
              }
            } finally {
              clearTimeout(deadline);
              if (!expired) {
                setBusy(null);
              }
            }
          },
        },
      ],
    );
  };

  return (
    <View style={styles.screen}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header navigation={navigation as any} title="Tiendas con tu sesión" backgroundColor={colors.heroField}
        isLight showBackButton />
      <Text style={styles.intro}>
        Cuando inicias sesión en una tienda desde el asistente, tu cuenta de esa tienda y su sesión se guardan
        cifradas para tu próxima compra, y solo se usan para iniciar sesión ahí. Aquí puedes borrarlas cuando
        quieras.
      </Text>
      {message ? (
        <InlineBanner message={message.text} variant={message.ok ? 'success' : 'error'} onDismiss={() => setMessage(null)}
          style={styles.banner} />
      ) : null}
      {loading && !data ? (
        <View style={styles.center}><ActivityIndicator color={colors.primaryDark} /></View>
      ) : error && !data ? (
        <View style={styles.center}><Text style={styles.empty}>No pude leer la lista. Revisa tu conexión.</Text></View>
      ) : otherAccount ? (
        <View style={styles.center}>
          <Text style={styles.empty}>Tus tiendas están en tu cuenta personal: cámbiate a ella para verlas.</Text>
        </View>
      ) : (
        <FlatList
          data={stores}
          keyExtractor={(site) => site}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          ListEmptyComponent={<Text style={styles.empty}>No hay tiendas con tu sesión guardada.</Text>}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Text style={styles.site} numberOfLines={1}>{item}</Text>
              <Button title="Cerrar sesión" variant="ghost" onPress={() => onForget(item)} loading={busy === item}
                disabled={busy !== null && busy !== item} />
            </View>
          )}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  intro: { fontSize: 14, lineHeight: 20, color: colors.text.secondary, padding: 16 },
  banner: { marginHorizontal: 16, marginBottom: 8 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  empty: { fontSize: 15, color: colors.text.secondary, textAlign: 'center', padding: 24 },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16,
    paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#E5E7EB',
  },
  site: { flex: 1, fontSize: 16, color: colors.text.primary, marginRight: 12 },
});

export default AgentStoresScreen;
