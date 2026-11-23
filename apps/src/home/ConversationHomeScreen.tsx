// Inicio in the conversation home
// (docs/designs/ai-assistant-first-redesign.md 7.3-7.4): the assistant
// conversation, under a header with the money line, Cobrar and the bell.
// HomeScreen stays mounted with it, drawing nothing: it keeps doing the
// background work Inicio always did (arrivals, swaps, the account switcher)
// and publishes the figures the header and the menu show.
import React, { useEffect, useMemo } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, View } from 'react-native';
import { useKeyboardOverlap } from './useKeyboardOverlap';
import { useIsFocused, useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { QrShowIcon } from '../components/QrPayIcon';
import AssistantSheet from '../assistant/AssistantSheet';
import { useAssistant } from '../assistant/AssistantContext';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useHeader } from '../contexts/HeaderContext';
import { HEADER_HEIGHT } from '../navigation/Header';
import { HomeScreen } from '../screens/HomeScreen';
import { formatUsd } from '../utils/monthSummary';
import { useAppDrawer } from './AppDrawer';
import { useHomeMoney } from './homeMoneyStore';
import { usePrimaryAction } from './usePrimaryAction';
import { logHomeNav } from '../services/homeNavAnalytics';

const INK = colors.onHeroField;
// The header re-renders with every published figure; the screen that
// publishes them re-renders only for its own reasons.
const HomeBackground = React.memo(HomeScreen);

function HomeHeader() {
  const navigation = useNavigation<any>();
  const drawer = useAppDrawer();
  const money = useHomeMoney();
  const { unreadNotifications } = useHeader();
  const { activeAccount } = useAccount();
  const type = (activeAccount?.type || 'personal').toLowerCase();
  const isBusiness = type === 'business';
  // Whenever it is not the personal account, the header says which one.
  const accountLine = isBusiness
    ? `${activeAccount?.isEmployee ? 'Empleado' : 'Negocio'} · ${activeAccount?.business?.name || activeAccount?.name || ''}`.replace(/ · $/, '')
    : null;

  const month = money.month.kind === 'month' && !money.masked ? money.month.summary.current : null;
  // Never under a total that is not there yet.
  const flows = accountLine || !money.ready ? null : month;
  const whole = (value: string) => formatUsd(value, { whole: true }).replace('US$', '');
  const moneyLabel = !money.ready
    ? 'Mi dinero. Abrir menú'
    : money.masked
      ? 'Mi dinero, saldo oculto. Abrir menú'
      : `Mi dinero: ${money.total}. Abrir menú`;

  return (
    <SafeAreaView edges={['top']} style={styles.headerSafe}>
      <View style={styles.header}>
        <Pressable
          onPress={() => { logHomeNav('header', 'menu'); drawer.open(); }}
          style={styles.menu}
          hitSlop={4}
          accessibilityRole="button"
          accessibilityLabel={drawer.hasNews ? 'Menú, hay novedades' : 'Menú'}
        >
          <Icon name="menu" size={24} color={INK} />
          {drawer.hasNews ? <View style={styles.menuDot} /> : null}
        </Pressable>

        {/* Two lines, so neither figure squeezes the other on a narrow
            phone: the total (opens the menu), and under it what came in and
            went out this month (opens "Tu mes" in one tap, as the month line
            on the old Inicio did). A business has its name on the first
            line instead, and finds the month in the menu. */}
        <View style={styles.moneyColumn}>
          <Pressable
            onPress={() => { logHomeNav('header', 'money'); drawer.open(); }}
            hitSlop={{ top: 10, bottom: flows ? 0 : 10 }}
            accessibilityRole="button"
            accessibilityLabel={accountLine ? `${accountLine}. ${moneyLabel}` : moneyLabel}
          >
            {accountLine ? <Text style={styles.account} numberOfLines={1}>{accountLine}</Text> : null}
            <Text style={styles.total} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.75}>
              {money.ready ? money.total : ' '}
            </Text>
          </Pressable>
          {flows ? (
            <Pressable
              onPress={() => { logHomeNav('header', 'month'); money.openMonth(); }}
              style={styles.flows}
              hitSlop={{ bottom: 10, left: 4, right: 16 }}
              accessibilityRole="button"
              accessibilityLabel={`Tu mes: entraron ${whole(flows.incomeUsd)} dólares y salieron ${whole(flows.spendingUsd)}. Abrir tu mes`}
            >
              {/* With the currency, like every other amount here: a bare
                  number beside a dollar total reads as something else. */}
              <Icon name="arrow-down-left" size={13} color={INK} />
              <Text style={styles.flow} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
                {formatUsd(flows.incomeUsd, { whole: true })}
              </Text>
              <Icon name="arrow-up-right" size={13} color={INK} style={styles.flowOut} />
              <Text style={styles.flow} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
                {formatUsd(flows.spendingUsd, { whole: true })}
              </Text>
              <Icon name="chevron-right" size={13} color={INK} />
            </Pressable>
          ) : null}
        </View>

        {/* A business charges from the composer's own button. */}
        {type === 'personal' ? (
          <Pressable
            onPress={() => { logHomeNav('header', 'charge'); navigation.navigate('Charge'); }}
            style={styles.round}
            hitSlop={2}
            accessibilityRole="button"
            accessibilityLabel="Cobrar"
          >
            <QrShowIcon size={20} color={INK} />
          </Pressable>
        ) : null}
        <Pressable
          onPress={() => { logHomeNav('header', 'notifications'); navigation.navigate('Notification'); }}
          style={styles.round}
          hitSlop={2}
          accessibilityRole="button"
          accessibilityLabel={unreadNotifications > 0 ? `Notificaciones, ${unreadNotifications} sin leer` : 'Notificaciones'}
        >
          <Icon name="bell" size={20} color={INK} />
          {unreadNotifications > 0 ? (
            <View style={styles.bellBadge}>
              <Text style={styles.bellBadgeText}>{unreadNotifications > 99 ? '99+' : unreadNotifications}</Text>
            </View>
          ) : null}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

export function ConversationHomeScreen() {
  const isFocused = useIsFocused();
  const drawer = useAppDrawer();
  const { isOpen: boxOpen, setHomeActive } = useAssistant();
  const money = useHomeMoney();
  const primary = usePrimaryAction();
  const { userProfile } = useAuth() as any;
  const composerPrimary = useMemo(() => (primary ? {
    kind: primary.kind,
    onPress: () => {
      logHomeNav('composer', primary.kind);
      primary.onPress();
    },
  } : null), [primary]);

  // Inicio is on screen: requests for the assistant come here and the
  // floating bubble steps away.
  const keyboard = useKeyboardOverlap();
  useEffect(() => {
    setHomeActive(isFocused);
    return () => setHomeActive(false);
  }, [isFocused, setHomeActive]);

  return (
    <View style={styles.screen} ref={keyboard.ref} onLayout={keyboard.onLayout} collapsable={false}>
      {/* A drag to the right anywhere on the conversation pulls the menu open.
          Android: the composer steps above the keyboard by what it really
          covers (useKeyboardOverlap); iOS pads the usual way. */}
      <KeyboardAvoidingView
        {...drawer.openGesture}
        style={[styles.screen, keyboard.overlap ? { paddingBottom: keyboard.overlap } : null]}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <HomeHeader />
        <AssistantSheet
          home={{
            active: isFocused && !boxOpen,
            name: userProfile?.firstName?.trim() || undefined,
            primary: composerPrimary,
            notice: money.notice,
          }}
        />
      </KeyboardAvoidingView>
      {/* Not drawn: Inicio's background work and its dialogs (see HomeScreen). */}
      <HomeBackground embedded />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#FFFFFF' },
  headerSafe: { backgroundColor: colors.heroField },
  header: {
    minHeight: HEADER_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    // The ☰ lands exactly where the shared Header draws it on the screens
    // opened from the drawer (x 20, same baseline): it must not jump.
    paddingLeft: 10,
    paddingRight: 14,
    paddingTop: 12,
    paddingBottom: 8,
  },
  menu: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  menuDot: {
    position: 'absolute',
    top: 8,
    right: 7,
    width: 10,
    height: 10,
    borderRadius: 5,
    // violet-700: 3.7:1 on the brand field (violet-500 is 2.2:1).
    backgroundColor: '#6D28D9',
    borderWidth: 2,
    borderColor: colors.heroField,
  },
  // 44 tall in all: the same header height as the screens opened from the menu.
  moneyColumn: { flex: 1, minHeight: 44, justifyContent: 'center' },
  account: { fontSize: 12, lineHeight: 16, fontWeight: '700', color: INK },
  total: { fontSize: 20, lineHeight: 24, fontWeight: '700', color: INK },
  // As wide as the column, so the whole second line is the target.
  flows: { flexDirection: 'row', alignItems: 'center', gap: 2, minHeight: 20 },
  flow: { flexShrink: 1, fontSize: 13, fontWeight: '700', color: INK },
  flowOut: { marginLeft: 6 },
  round: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.35)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  bellBadge: {
    position: 'absolute',
    top: -2,
    right: -2,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 4,
    backgroundColor: '#DC2626',
    alignItems: 'center',
    justifyContent: 'center',
  },
  bellBadgeText: { fontSize: 10, fontWeight: '700', color: '#FFFFFF' },
});
