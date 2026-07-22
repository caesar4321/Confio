// Blocked account — the ban flow's ANNOUNCEMENT surface
// (docs/plans/salida-de-emergencia-design.md, "Ban work package").
//
// The emergency exit is this screen's CTA, not its replacement: a banned
// user first learns WHAT happened and how to appeal, then — because we
// enforce accounts, never funds — gets the one-tap path to withdraw.
// Everything here is static or chain-side: the security middleware 403s
// every authenticated request for banned users, so this screen must not
// depend on any server data (the ban reason lives in UserBan server-side
// and is deliberately not fetched — there is no endpoint a banned user
// could reach).
//
// «Reintentar» probes with a throwaway authenticated query: success means
// the ban is over (banClearLink wipes the flag) and we return to Main;
// another 403 re-marks and we stay.

import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Linking, StatusBar, ActivityIndicator, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { gql } from '@apollo/client';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { colors } from '../config/theme';
import { emergencyStore } from '../services/emergencyExit/store';
import { isBanSignaled } from '../services/emergencyExit/banSignal';

const PING = gql`query BanRetryPing { __typename }`;

export const BlockedAccountScreen: React.FC = () => {
  const navigation = useNavigation<any>();
  const [retrying, setRetrying] = useState(false);

  const openSupport = async () => {
    try {
      await Linking.openURL('tg://resolve?domain=confio4world');
    } catch {
      Linking.openURL('https://t.me/confio4world').catch(() => {});
    }
  };

  const retry = async () => {
    setRetrying(true);
    try {
      const { apolloClient } = await import('../apollo/client');
      await apolloClient.query({ query: PING, fetchPolicy: 'network-only' }).catch(() => {});
      // Success cleared the flag (banClearLink); a 403 re-marked it.
      if (!(await isBanSignaled(emergencyStore))) {
        navigation.reset({ index: 0, routes: [{ name: 'BottomTabs' }] });
      }
    } finally {
      setRetrying(false);
    }
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <BrandFieldBackground id="blockedField" ringCy="30%" />
          <View style={styles.headerInner}>
            <View style={styles.heroIconRing}>
              <Icon name="slash" size={26} color={colors.white} />
            </View>
            <Text style={styles.heroTitle}>Tu cuenta fue suspendida</Text>
            <Text style={styles.heroSub}>
              El acceso a Confío está bloqueado mientras revisamos tu caso.
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* The regulatory core: we enforce accounts, never funds. */}
        <View style={styles.moneyCard}>
          <Icon name="shield" size={18} color={colors.primaryDark} />
          <Text style={styles.moneyText}>
            Tu dinero no está bloqueado. Está en la blockchain, sigue siendo
            tuyo, y puedes retirarlo ahora mismo — no podemos impedirlo.
          </Text>
        </View>

        <TouchableOpacity
          style={styles.exitBtn}
          onPress={() => navigation.navigate('EmergencyExit')}
        >
          <Icon name="log-out" size={17} color={colors.white} />
          <Text style={styles.exitBtnText}>Retirar mi dinero</Text>
        </TouchableOpacity>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>¿Crees que es un error?</Text>
          <Text style={styles.bodyText}>
            Escríbenos y revisaremos tu caso. Recuerda: nadie de Confío te
            pedirá jamás tus claves ni que muevas tu dinero a otra dirección.
          </Text>
          <TouchableOpacity style={styles.supportBtn} onPress={openSupport}>
            <Icon name="message-circle" size={16} color={colors.primaryDark} />
            <Text style={styles.supportBtnText}>Contactar soporte</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={styles.retryBtn} onPress={retry} disabled={retrying}>
          {retrying
            ? <ActivityIndicator size="small" color={colors.text.secondary} />
            : <Text style={styles.retryText}>Ya se resolvió — reintentar</Text>}
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  header: { backgroundColor: colors.primary, overflow: 'hidden' },
  headerInner: { paddingHorizontal: 24, paddingTop: 28, paddingBottom: 30, alignItems: 'center' },
  heroIconRing: {
    width: 56, height: 56, borderRadius: 28, borderWidth: 2, borderColor: 'rgba(255,255,255,0.55)',
    alignItems: 'center', justifyContent: 'center', marginBottom: 12,
  },
  heroTitle: { fontSize: 22, fontWeight: 'bold', color: colors.white, textAlign: 'center' },
  heroSub: {
    fontSize: 13, lineHeight: 19, color: colors.white, opacity: 0.92,
    textAlign: 'center', marginTop: 6,
  },
  scroll: { padding: 16, paddingBottom: 48 },
  moneyCard: {
    flexDirection: 'row', gap: 10, alignItems: 'flex-start',
    backgroundColor: colors.white, borderRadius: 16, borderWidth: 1,
    borderColor: colors.border, padding: 16, marginBottom: 12,
  },
  moneyText: { flex: 1, fontSize: 14, lineHeight: 21, color: colors.text.primary, fontWeight: '600' },
  exitBtn: {
    flexDirection: 'row', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 12,
    paddingVertical: 15, alignItems: 'center', justifyContent: 'center', marginBottom: 12,
  },
  exitBtnText: { color: colors.white, fontWeight: '700', fontSize: 15.5 },
  card: {
    backgroundColor: colors.white, borderRadius: 16, borderWidth: 1,
    borderColor: colors.border, padding: 16, marginBottom: 12,
  },
  cardTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary, marginBottom: 6 },
  bodyText: { fontSize: 13.5, lineHeight: 20, color: colors.text.secondary },
  supportBtn: {
    flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: colors.primaryDark, borderRadius: 10,
    paddingVertical: 11, marginTop: 12,
  },
  supportBtnText: { color: colors.primaryDark, fontWeight: '600', fontSize: 14 },
  retryBtn: { alignSelf: 'center', paddingVertical: 10, paddingHorizontal: 20 },
  retryText: { fontSize: 13, color: colors.text.secondary, fontWeight: '600' },
});

export default BlockedAccountScreen;
