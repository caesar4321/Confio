import React, { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { IdentityStatusLine } from '../components/IdentityStatusLine';
import { LINK_INVITE, LINK_SEND_ERRORS, claimLink } from '../services/linkSend';

/**
 * Receiving a link send (confio.lat/r/<ref>#<key>). Shows who sent it and how
 * much, then signs with the link's key so the money lands in the signed-in
 * user's personal account (services/linkSend.ts).
 */
export const LinkClaimScreen = () => {
  const { publicRef, keyHex } = (useRoute().params || {}) as { publicRef: string; keyHex: string };
  // Opening another link reuses this route with new params: remount per link
  // so one link's state (claimed, errors, a request in flight) never shows on
  // another.
  return <LinkClaim key={publicRef} publicRef={publicRef} keyHex={keyHex} />;
};

const LinkClaim = ({ publicRef, keyHex }: { publicRef: string; keyHex: string }) => {
  const navigation = useNavigation<any>();
  const { data, loading, error, refetch } = useQuery(LINK_INVITE, {
    variables: { publicRef },
    fetchPolicy: 'network-only',
  });
  const [claiming, setClaiming] = useState(false);
  const [claimed, setClaimed] = useState(false);
  const [problem, setProblem] = useState('');
  const link = data?.linkInvite;

  const receive = async () => {
    if (claiming) return;
    setClaiming(true);
    setProblem('');
    try {
      await claimLink(publicRef, keyHex);
      setClaimed(true);
    } catch (e: any) {
      setProblem(LINK_SEND_ERRORS[e?.message] || 'No pudimos recibir el envío. Revisa tu conexión e inténtalo de nuevo.');
      refetch().catch(() => {});
    } finally {
      setClaiming(false);
    }
  };

  const amount = link ? `US$${Number(link.amount).toFixed(2)}` : '';
  const sender = link ? (link.senderName || `@${link.senderUsername}`) : '';
  const expired = link?.expiresAt && new Date(link.expiresAt).getTime() <= Date.now();

  let body: React.ReactNode;
  if (loading && !link) {
    body = <ActivityIndicator color={colors.primary} style={{ marginTop: 32 }} />;
  } else if (error || !link) {
    body = <Text style={styles.body}>{error ? 'No pudimos abrir el envío. Revisa tu conexión.' : LINK_SEND_ERRORS.link_not_found}</Text>;
  } else if (claimed || link.status === 'claiming' || link.status === 'claimed') {
    body = (
      <>
        <Icon name="check-circle" size={44} color={colors.primaryDark} />
        <Text style={styles.title}>{claimed ? `Recibiste ${amount}` : 'Este envío ya fue recibido'}</Text>
        <Text style={styles.body}>
          {claimed ? 'Llega a tu cuenta personal en unos segundos.' : 'Si fuiste tú, ya está en tu saldo.'}
        </Text>
      </>
    );
  } else if (link.isMine) {
    body = <Text style={styles.body}>{LINK_SEND_ERRORS.link_is_yours} Compártelo con la persona a quien se lo enviaste.</Text>;
  } else if (link.status !== 'pending' || expired) {
    body = <Text style={styles.body}>{expired ? LINK_SEND_ERRORS.link_expired : LINK_SEND_ERRORS.link_not_claimable}</Text>;
  } else {
    body = (
      <>
        <Text style={styles.from}>{sender} te envió</Text>
        <IdentityStatusLine verified={Boolean(link.senderVerified)} />
        <Text style={styles.amount}>{amount}</Text>
        <Text style={styles.body}>Llega a tu cuenta personal de Confío.</Text>
        {problem ? <Text style={styles.problem}>{problem}</Text> : null}
        <Pressable style={[styles.primary, claiming && styles.disabled]} disabled={claiming}
          onPress={() => { void receive(); }} accessibilityRole="button">
          {claiming ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryText}>Recibir {amount}</Text>}
        </Pressable>
      </>
    );
  }

  return (
    <View style={styles.container}>
      <Header title="Recibir envío" navigation={navigation} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <View style={styles.card}>{body}</View>
    </View>
  );
};

export default LinkClaimScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  card: {
    margin: 16, padding: 20, gap: 12, alignItems: 'center', borderRadius: 14,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  from: { fontSize: 15, color: colors.textSecondary },
  amount: { fontSize: 36, fontWeight: '700', color: colors.dark },
  title: { fontSize: 18, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  body: { fontSize: 14, color: colors.textSecondary, textAlign: 'center' },
  problem: { fontSize: 14, color: colors.danger, textAlign: 'center' },
  primary: {
    alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center', paddingVertical: 14, borderRadius: 24,
    backgroundColor: colors.primaryDark, marginTop: 4,
  },
  primaryText: { fontSize: 16, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.6 },
});
