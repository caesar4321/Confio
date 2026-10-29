import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { IdentityStatusLine } from '../components/IdentityStatusLine';
import { BylineAvatar } from '../components/PostByline';
import { LINK_INVITE, LINK_INVITE_SENDER, LINK_SEND_ERRORS, claimLink } from '../services/linkSend';

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

const daysLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  return ms > 0 ? Math.ceil(ms / 86_400_000) : 0;
};

const LinkClaim = ({ publicRef, keyHex }: { publicRef: string; keyHex: string }) => {
  const navigation = useNavigation<any>();
  const { data, loading, error, refetch } = useQuery(LINK_INVITE, {
    variables: { publicRef },
    fetchPolicy: 'network-only',
  });
  // Photo and profile link: extras. Without them the initial stands in and
  // the history button is left out.
  const { data: senderData } = useQuery(LINK_INVITE_SENDER, {
    variables: { publicRef },
    fetchPolicy: 'cache-first',
    errorPolicy: 'ignore',
  });
  const [claiming, setClaiming] = useState(false);
  const [claimed, setClaimed] = useState(false);
  const [problem, setProblem] = useState('');
  const link = data?.linkInvite;
  const senderUserId = senderData?.linkInvite?.senderUserId || null;
  const avatarUrl = senderData?.linkInvite?.senderAvatarUrl || null;
  const [avatarFailed, setAvatarFailed] = useState(false);

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
  const handle = link?.senderUsername ? `@${link.senderUsername}` : '';
  const sender = link ? (link.senderName || handle) : '';
  const left = daysLeft(link?.expiresAt);
  const expired = left === 0;

  const openHistory = () => {
    if (!senderUserId || !link) return;
    navigation.navigate('FriendDetail', {
      friendId: String(senderUserId),
      friendName: sender,
      friendAvatar: (sender || '?').replace(/^@/, '').charAt(0).toUpperCase(),
      isOnConfio: true,
      friendConfioUsername: link.senderUsername,
      friendConfioFirstName: link.senderName || '',
    });
  };
  const goHome = () => {
    navigation.navigate('BottomTabs', { screen: 'Home' });
  };

  const avatar = (size: number) => (
    <BylineAvatar name={sender || '?'} avatarUrl={avatarFailed ? null : avatarUrl} size={size}
      onImageError={() => setAvatarFailed(true)} />
  );

  let content: React.ReactNode;
  if (loading && !link) {
    content = <ActivityIndicator color={colors.primary} style={{ marginTop: 48 }} />;
  } else if (error || !link) {
    content = (
      <Notice icon="link-2" text={error ? 'No pudimos abrir el envío. Revisa tu conexión.' : LINK_SEND_ERRORS.link_not_found} />
    );
  } else if (claimed) {
    content = (
      <Received amount={amount} sender={sender} avatar={avatar(44)}
        onHistory={senderUserId ? openHistory : null} onDone={goHome} />
    );
  } else if (link.status === 'claiming' || link.status === 'claimed') {
    content = <Notice icon="check-circle" title="Este envío ya fue recibido" text="Si fuiste tú, ya está en tu saldo." />;
  } else if (link.isMine) {
    content = <Notice icon="send" text={`${LINK_SEND_ERRORS.link_is_yours} Compártelo con la persona a quien se lo enviaste.`} />;
  } else if (link.status !== 'pending' || expired) {
    content = <Notice icon="clock" text={expired ? LINK_SEND_ERRORS.link_expired : LINK_SEND_ERRORS.link_not_claimable} />;
  } else {
    content = (
      <>
        <View style={styles.hero}>
          {avatar(72)}
          <Text style={styles.from}>
            <Text style={styles.fromName}>{sender}</Text> te envió
          </Text>
          {link.senderName && handle ? <Text style={styles.handle}>{handle}</Text> : null}
          <Text style={styles.amount} adjustsFontSizeToFit numberOfLines={1}>{amount}</Text>
          <IdentityStatusLine verified={Boolean(link.senderVerified)} explain={false} />
        </View>
        <View style={styles.facts}>
          <Fact icon="user" text="Llega a tu cuenta personal de Confío." />
          <Fact icon="gift" text="Recibirlo no te cuesta nada." />
          {left ? (
            <Fact icon="clock" text={left === 1
              ? 'Recíbelo hoy: si no, vuelve a quien te lo envió.'
              : `Tienes ${left} días para recibirlo; si no, vuelve a quien te lo envió.`} />
          ) : null}
        </View>
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
      <Header title={claimed ? '' : 'Recibir envío'} navigation={navigation}
        onBackPress={() => (claimed ? goHome() : navigation.goBack())}
        backgroundColor={colors.background} isLight={false} />
      <ScrollView contentContainerStyle={styles.content}>{content}</ScrollView>
    </View>
  );
};

/** The moment it lands: a check that pops in, then what to do next. */
const Received = ({ amount, sender, avatar, onHistory, onDone }: {
  amount: string; sender: string; avatar: React.ReactNode;
  onHistory: (() => void) | null; onDone: () => void;
}) => {
  const pop = useRef(new Animated.Value(0)).current;
  const rise = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.sequence([
      Animated.spring(pop, { toValue: 1, friction: 5, tension: 120, useNativeDriver: true }),
      Animated.timing(rise, { toValue: 1, duration: 260, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
    ]).start();
  }, [pop, rise]);
  const riseStyle = {
    opacity: rise,
    transform: [{ translateY: rise.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) }],
  };
  return (
    <View style={styles.received}>
      <Animated.View style={[styles.checkRing, { opacity: pop, transform: [{ scale: pop }] }]}>
        <View style={styles.checkDot}>
          <Icon name="check" size={40} color={colors.white} />
        </View>
      </Animated.View>
      <Animated.View style={[styles.receivedText, riseStyle]}>
        <Text style={styles.receivedLabel}>Recibiste</Text>
        <Text style={styles.amount} adjustsFontSizeToFit numberOfLines={1}>{amount}</Text>
        <View style={styles.fromRow}>
          {avatar}
          <Text style={styles.from}>de <Text style={styles.fromName}>{sender}</Text></Text>
        </View>
        <Text style={styles.body}>Ya está en tu saldo. Puede tardar unos segundos en aparecer.</Text>
      </Animated.View>
      <Animated.View style={[styles.actions, riseStyle]}>
        <Pressable style={styles.primary} onPress={onDone} accessibilityRole="button">
          <Text style={styles.primaryText}>Ver mi saldo</Text>
        </Pressable>
        {onHistory ? (
          <Pressable style={styles.secondary} onPress={onHistory} accessibilityRole="button">
            <Text style={styles.secondaryText}>Enviarle algo de vuelta</Text>
          </Pressable>
        ) : null}
      </Animated.View>
    </View>
  );
};

const Fact = ({ icon, text }: { icon: string; text: string }) => (
  <View style={styles.fact}>
    <View style={styles.factIcon}><Icon name={icon} size={15} color={colors.flowIn.textSmall} /></View>
    <Text style={styles.factText}>{text}</Text>
  </View>
);

const Notice = ({ icon, title, text }: { icon: string; title?: string; text: string }) => (
  <View style={styles.notice}>
    <View style={styles.noticeIcon}><Icon name={icon} size={26} color={colors.textSecondary} /></View>
    {title ? <Text style={styles.title}>{title}</Text> : null}
    <Text style={styles.body}>{text}</Text>
  </View>
);

export default LinkClaimScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { flexGrow: 1, padding: 20, paddingBottom: 32, gap: 20 },
  hero: {
    alignItems: 'center', gap: 6, paddingVertical: 28, paddingHorizontal: 16, borderRadius: 20,
    backgroundColor: colors.primarySoft,
  },
  from: { fontSize: 16, color: colors.textSecondary, marginTop: 10, textAlign: 'center' },
  fromName: { fontWeight: '700', color: colors.dark },
  handle: { fontSize: 13, color: colors.textSecondary },
  amount: { fontSize: 44, fontWeight: '800', color: colors.dark, marginVertical: 4 },
  facts: { gap: 12, paddingHorizontal: 4 },
  fact: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  factIcon: {
    width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  factText: { flex: 1, fontSize: 14, lineHeight: 20, color: colors.dark },
  title: { fontSize: 18, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  body: { fontSize: 14, lineHeight: 20, color: colors.textSecondary, textAlign: 'center' },
  problem: { fontSize: 14, color: colors.danger, textAlign: 'center' },
  primary: {
    alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center', paddingVertical: 15, borderRadius: 24,
    backgroundColor: colors.primaryDark,
  },
  primaryText: { fontSize: 16, fontWeight: '700', color: colors.white },
  secondary: {
    alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center', paddingVertical: 14, borderRadius: 24,
    borderWidth: 1, borderColor: colors.primaryMuted, backgroundColor: colors.background,
  },
  secondaryText: { fontSize: 16, fontWeight: '600', color: colors.successText },
  disabled: { opacity: 0.6 },
  received: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 24, paddingTop: 24 },
  checkRing: {
    width: 112, height: 112, borderRadius: 56, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  checkDot: {
    width: 80, height: 80, borderRadius: 40, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryDark,
  },
  receivedText: { alignItems: 'center', gap: 4, alignSelf: 'stretch' },
  receivedLabel: { fontSize: 16, color: colors.textSecondary },
  fromRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
  actions: { alignSelf: 'stretch', gap: 10, marginTop: 8 },
  notice: { alignItems: 'center', gap: 12, paddingTop: 48, paddingHorizontal: 12 },
  noticeIcon: {
    width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.neutral,
  },
});
