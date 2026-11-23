// The drawer of the conversation home
// (docs/designs/ai-assistant-first-redesign.md 7.3-7.4): the money block on
// top, the product screens, and the profile merged with the account switcher
// at the foot. It opens from ☰, a tap on the header's total, or a drag to
// the right on the conversation, and it follows the finger both ways
// (useDrawerMotion; not from the screen's very edge, which on Android
// belongs to the system's back gesture).
//
// A plain overlay inside the tab navigator, not a Modal: what its rows open
// (dialogs, the assistant's box) are Modals themselves, and iOS cannot
// present one modal from under another.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  Animated,
  BackHandler,
  findNodeHandle,
  type GestureResponderHandlers,
  type ViewProps,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import { useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useHeader } from '../contexts/HeaderContext';
import { GET_DIRECT_UNREAD_SUMMARY, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import { useOptionalAssistant } from '../assistant/AssistantContext';
import { navigationRef } from '../navigation/RootNavigation';
import { peekBadge, useCommunityPeek } from '../services/communityPeek';
import { formatUsd, MASK } from '../utils/monthSummary';
import {
  HomeMoneyStoreProvider, createHomeMoneyStore, registerHomeMenu, registerHomeMoneyReader, useHomeMoney,
} from './homeMoneyStore';
import { logHomeNav } from '../services/homeNavAnalytics';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { drawerWidth, useDrawerMotion } from './useDrawerMotion';

const EMERALD = '#047857';
// Opening the menu twice in a row does not ask for the balances twice.
const REFRESH_EVERY_MS = 20_000;
const INK = '#111827';
const MUTED = '#4B5563';

type DrawerState = {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  /** Something new behind ☰ (Comunidad posts, messages): the dot on the icon. */
  hasNews: boolean;
  /** Back to the conversation. */
  goHome: () => void;
  /** Spread on the conversation: a drag to the right pulls the menu open. */
  openGesture: GestureResponderHandlers;
};

const DrawerContext = createContext<DrawerState | null>(null);

export function useAppDrawer(): DrawerState {
  const value = useContext(DrawerContext);
  if (!value) {
    throw new Error('useAppDrawer must be used inside AppDrawerProvider');
  }
  return value;
}

/** For headers that also render outside the conversation home (five tabs). */
export function useOptionalAppDrawer(): DrawerState | null {
  return useContext(DrawerContext);
}

// `pop`: the drawer only opens from its own tab screens, where this simply
// switches tab. The one caller that can run over a pushed screen is "Mi
// dinero" asked for from the assistant's box: it must come back to the shell
// whose list it is opening, not push a new one on top.
const goTab = (screen: string, params?: object) => {
  (navigationRef as any).navigate('Main', { screen: 'BottomTabs', params: { screen, params }, pop: true });
};

export function AppDrawerProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const { activeAccount } = useAccount();
  const { isAuthenticated } = useAuth() as any;
  const contextKey = activeAccount?.id || 'no-account';
  const communityPeek = useCommunityPeek();
  const communityBadge = peekBadge(communityPeek);
  // The floating bubble keeps both counts fresh; here they are only read.
  const { data: unreadData } = useQuery(GET_MESSAGE_INBOX_UNREAD_COUNT, {
    variables: { contextKey },
    fetchPolicy: 'cache-first',
    skip: !isAuthenticated,
  });
  const { data: dmData } = useQuery(GET_DIRECT_UNREAD_SUMMARY, {
    fetchPolicy: 'cache-first',
    errorPolicy: 'ignore',
    skip: !isAuthenticated,
  });
  const dm = dmData?.directUnreadSummary;
  const directUnread = (dm?.unreadMessages || 0) + (dm?.requests || 0);
  const unreadMessages = (unreadData?.messageInboxUnreadCount || 0) + directUnread;

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const goHome = useCallback(() => goTab('Home'), []);
  // "Muéstrame mi dinero": the assistant's `home` destination opens the menu,
  // where the person's money is. (From the box over a pushed screen this
  // comes back to this shell's Inicio first.) A Cuenta inteligente context
  // keeps its own home and has no menu.
  const hasMenu = (activeAccount?.type || 'personal').toLowerCase() !== 'smart';
  const openFromAssistant = useCallback(() => {
    goTab('Home');
    setIsOpen(true);
  }, []);
  useEffect(() => (hasMenu ? registerHomeMenu(openFromAssistant) : undefined), [openFromAssistant, hasMenu]);
  // This shell's own figures (see homeMoneyStore).
  const moneyStore = useRef(createHomeMoneyStore()).current;
  // The assistant opens a wallet as its tile here does.
  useEffect(() => (hasMenu ? registerHomeMoneyReader(moneyStore.get) : undefined), [hasMenu, moneyStore]);
  const { width: screenWidth } = useWindowDimensions();
  const panelWidth = drawerWidth(screenWidth);
  const motion = useDrawerMotion(isOpen, setIsOpen, panelWidth);

  // Another account: its menu starts closed.
  useEffect(() => {
    setIsOpen(false);
  }, [activeAccount?.id]);

  // The assistant's bubble floats above every screen, this menu included.
  const shellAssistant = useOptionalAssistant();
  const setMenuOpen = shellAssistant?.setMenuOpen;
  useEffect(() => {
    setMenuOpen?.(isOpen);
    return () => setMenuOpen?.(false);
  }, [isOpen, setMenuOpen]);

  const value = useMemo(
    () => ({
      isOpen, open, close, hasNews: communityBadge !== null || unreadMessages > 0, goHome, openGesture: motion.openGesture,
    }),
    [isOpen, open, close, communityBadge, unreadMessages, goHome, motion.openGesture],
  );

  return (
    <HomeMoneyStoreProvider value={moneyStore}>
    <DrawerContext.Provider value={value}>
      <View
        style={styles.behind}
        accessibilityElementsHidden={isOpen}
        importantForAccessibility={isOpen ? 'no-hide-descendants' : 'auto'}
      >
        {children}
      </View>
      <DrawerPanel
        isOpen={isOpen}
        mounted={motion.mounted}
        progress={motion.progress}
        width={panelWidth}
        closeGesture={motion.closeGesture}
        sidewaysScroller={motion.sidewaysScroller}
        onClose={close}
        onGoHome={goHome}
        communityBadge={communityBadge}
        unreadMessages={unreadMessages}
        directUnread={directUnread}
      />
    </DrawerContext.Provider>
    </HomeMoneyStoreProvider>
  );
}

function Row({ icon, mark, label, onPress, badge, badgeNoun = 'sin leer', dot }: {
  icon?: string; mark?: React.ReactNode; label: string; onPress: () => void; badge?: string; badgeNoun?: string; dot?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={badge ? `${label}, ${badge} ${badgeNoun}` : dot ? `${label}, hay novedades` : label}
    >
      {mark ?? <Icon name={icon as string} size={20} color={INK} />}
      <Text style={styles.rowLabel} numberOfLines={1}>{label}</Text>
      {badge ? (
        <View style={styles.badge}><Text style={styles.badgeText}>{badge}</Text></View>
      ) : dot ? <View style={styles.dot} /> : null}
    </Pressable>
  );
}

function DrawerPanel({
  isOpen, mounted, progress, width, closeGesture, sidewaysScroller, onClose, onGoHome, communityBadge, unreadMessages, directUnread,
}: {
  isOpen: boolean;
  /** Drawn at all: open, being dragged, or still sliding away. */
  mounted: boolean;
  progress: Animated.Value;
  width: number;
  closeGesture: ViewProps;
  sidewaysScroller: ViewProps;
  onClose: () => void;
  onGoHome: () => void;
  communityBadge: string | null;
  unreadMessages: number;
  directUnread: number;
}) {
  const insets = useSafeAreaInsets();
  const money = useHomeMoney();
  const { activeAccount } = useAccount();
  const { userProfile } = useAuth() as any;
  const { currentAccountAvatar } = useHeader();
  // The accounts, opened in place at the foot. Closed again with the menu.
  const [switching, setSwitching] = useState(false);
  useEffect(() => {
    if (!isOpen) setSwitching(false);
  }, [isOpen]);
  const assistant = useOptionalAssistant();

  // Android back closes the drawer before anything else.
  useEffect(() => {
    if (!isOpen) return undefined;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      onClose();
      return true;
    });
    return () => sub.remove();
  }, [isOpen, onClose]);

  // The menu is where the person reads their money: it asks for the
  // balances again each time it opens (at most once in a while).
  const refreshedAt = useRef(0);
  // Read at the moment it opens: a new snapshot while it is open (the eye, a
  // balance tick) must not ask again.
  const refresh = useRef(money.refresh);
  refresh.current = money.refresh;
  useEffect(() => {
    if (isOpen && Date.now() - refreshedAt.current > REFRESH_EVERY_MS) {
      refreshedAt.current = Date.now();
      refresh.current();
    }
  }, [isOpen]);

  // The wallet strip takes sideways drags only when it has more wallets than
  // fit: with two tiles a drag to the left there still closes the menu.
  const stripSize = useRef({ layout: 0, content: 0 });
  const [stripScrolls, setStripScrolls] = useState(true);
  const measureStrip = (next: Partial<{ layout: number; content: number }>) => {
    Object.assign(stripSize.current, next);
    const { layout, content } = stripSize.current;
    if (layout > 0 && content > 0) {
      setStripScrolls(content > layout + 1);
    }
  };

  // A screen reader lands inside the menu when it opens.
  const firstItem = useRef<View | null>(null);
  useEffect(() => {
    if (!isOpen || !mounted) return undefined;
    const timer = setTimeout(() => {
      const node = firstItem.current ? findNodeHandle(firstItem.current) : null;
      if (node) AccessibilityInfo.setAccessibilityFocus(node);
    }, 300);
    return () => clearTimeout(timer);
  }, [isOpen, mounted]);

  if (!mounted) {
    return null;
  }

  const type = (activeAccount?.type || 'personal').toLowerCase();
  const isBusiness = type === 'business';
  const isEmployee = !!activeAccount?.isEmployee;
  // Every door of the menu: log which one, close, then act.
  const leave = (target: string, go: () => void) => () => {
    logHomeNav('drawer', target);
    onClose();
    go();
  };
  // The same words the header uses for the account on screen.
  const accountKind = isEmployee ? 'Empleado' : isBusiness ? 'Negocio' : 'Personal';
  const accountName = isBusiness
    ? activeAccount?.business?.name || activeAccount?.name || 'Negocio'
    : userProfile?.firstName || activeAccount?.name || 'Tu cuenta';
  // The current account is the foot's own row: the list is the others.
  const otherAccounts = money.accounts.filter((account) => !account.selected);
  const month = money.month;
  // With the currency, like the header's (the line shrinks to fit beside
  // "Tu mes" on a narrow phone rather than dropping it).
  const whole = (value: string) => formatUsd(value, { whole: true });
  const monthLine = month.kind === 'month'
    ? money.masked
      ? `Entró ${MASK} · Salió ${MASK}`
      : `Entró ${whole(month.summary.current.incomeUsd)} · Salió ${whole(month.summary.current.spendingUsd)}`
    : month.kind === 'invite' ? 'Mira lo que entra y sale' : null;
  const translateX = progress.interpolate({ inputRange: [0, 1], outputRange: [-width, 0] });

  return (
    <View
      style={styles.overlay}
      // Sliding away it takes no more taps: a second tap on a row must not
      // act twice.
      pointerEvents={isOpen ? 'box-none' : 'none'}
      accessibilityViewIsModal
      onAccessibilityEscape={onClose}
      {...closeGesture}
    >
      <Animated.View style={[styles.scrim, { opacity: progress }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar menú" />
      </Animated.View>
      <Animated.View
        style={[styles.panel, { width, paddingTop: insets.top + 8, transform: [{ translateX }] }]}
      >
        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          {/* ── Money ── */}
          <View style={styles.money}>
            <View style={styles.totalRow}>
              {/* This is the place for the person's money: nothing to open
                  behind it. */}
              <View
                ref={firstItem}
                style={styles.totalPress}
                accessible
                accessibilityRole="text"
                accessibilityLabel={!money.ready ? 'Mi dinero' : money.masked ? 'Mi dinero, saldo oculto' : `Mi dinero, ${money.total}`}
              >
                <Text style={styles.totalLabel}>Mi dinero</Text>
                {/* Not known yet is a dash, never a zero and never the mask. */}
                <Text style={styles.total} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
                  {money.ready ? money.total : '—'}
                </Text>
              </View>
              {money.currencyCode ? (
                <Pressable
                  onPress={() => { logHomeNav('drawer', 'currency'); money.toggleCurrency(); }}
                  style={({ pressed }) => [styles.currency, pressed && styles.pressed]}
                  hitSlop={6}
                  accessibilityRole="button"
                  accessibilityLabel={money.currencyHint}
                >
                  <Text style={styles.currencyText}>{money.currencyCode}</Text>
                  <Icon name="chevron-down" size={14} color={INK} />
                </Pressable>
              ) : null}
              {money.canToggle ? (
                <Pressable
                  onPress={money.toggleBalance}
                  style={styles.eye}
                  hitSlop={6}
                  accessibilityRole="button"
                  accessibilityLabel={money.masked ? 'Mostrar saldo' : 'Ocultar saldo'}
                >
                  <Icon name={money.masked ? 'eye-off' : 'eye'} size={18} color={MUTED} />
                </Pressable>
              ) : null}
            </View>

            {monthLine ? (
              <Pressable
                onPress={leave('month', money.openMonth)}
                style={({ pressed }) => [styles.month, pressed && styles.pressed]}
                accessibilityRole="button"
                accessibilityLabel={`Tu mes. ${monthLine}`}
              >
                <Text style={styles.monthText} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>{monthLine}</Text>
                <Text style={styles.monthLink}>Tu mes</Text>
                <Icon name="chevron-right" size={16} color={EMERALD} />
              </Pressable>
            ) : null}

            {!money.tiles.length ? (
              // Before the first balances answer: two blank tiles hold the
              // strip's place, so the rows below do not jump when it fills in.
              <View style={[styles.tilesScroll, styles.tiles, styles.tilesPending]} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
                {[0, 1].map((i) => (
                  <View key={i} style={[styles.tile, styles.tilePending]}>
                    <Text style={styles.tileLabel} numberOfLines={1}> </Text>
                    <Text style={styles.tileAmount} numberOfLines={1}>—</Text>
                  </View>
                ))}
              </View>
            ) : (
              // Its sideways drag scrolls the wallets; it never pushes the menu away.
              <View style={styles.tilesScroll} {...(stripScrolls ? sidewaysScroller : null)}>
              <ScrollView
                horizontal
                onLayout={(e) => measureStrip({ layout: e.nativeEvent.layout.width })}
                onContentSizeChange={(contentWidth) => measureStrip({ content: contentWidth })}
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.tiles}
              >
                {money.tiles.map((tile) => (
                  <Pressable
                    key={tile.key}
                    onPress={leave(`wallet_${tile.key}`, tile.onPress)}
                    style={({ pressed }) => [styles.tile, tile.amount === null && styles.tileOffer, pressed && styles.pressed]}
                    accessibilityRole="button"
                    accessibilityLabel={tile.accessibilityLabel}
                  >
                    <Text style={styles.tileLabel} numberOfLines={1}>{tile.label}</Text>
                    {tile.amount === null ? (
                      <Text style={styles.tileOfferText} numberOfLines={1}>{tile.offerLabel}</Text>
                    ) : (
                      <Text style={styles.tileAmount} numberOfLines={1}>{tile.amount}</Text>
                    )}
                  </Pressable>
                ))}
              </ScrollView>
              </View>
            )}

            {money.actions.length ? (
              <View style={styles.actions}>
                {money.actions.map((action) => (
                  <Pressable
                    key={action.id}
                    onPress={leave(action.id, action.onPress)}
                    style={({ pressed }) => [styles.action, action.filled && styles.actionFilled, pressed && styles.actionPressed]}
                    accessibilityRole="button"
                    accessibilityLabel={action.label}
                  >
                    <Icon name={action.icon} size={18} color={action.filled ? '#FFFFFF' : INK} />
                    <Text style={[styles.actionText, action.filled && styles.actionTextFilled]}>{action.label}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>

          {/* ── Products ── */}
          <View style={styles.section}>
            {/* First, and always there: without a tab bar this row is the way
                back to the conversation from every other screen (iOS has no
                hardware back). */}
            <Row icon="home" label="Inicio" onPress={leave('home', onGoHome)} />
            <Row icon="trending-up" label="Invertir" onPress={leave('invest', () => goTab('Invest', { segment: 'invest', at: Date.now() }))} />
            <Row
              icon="users"
              label="Comunidad"
              onPress={leave('community', () => goTab('Invest', { segment: 'community', at: Date.now() }))}
              badge={communityBadge || undefined}
              badgeNoun={communityBadge === '1' ? 'publicación nueva' : 'publicaciones nuevas'}
              dot={communityBadge === ''}
            />
            <Row icon="shopping-bag" label="Comprar" onPress={leave('comprar', () => goTab('Comprar'))} />
            {money.openSmart ? (
              <Row
                mark={<View style={styles.rowMark}><CuentaInteligenteMark size={22} /></View>}
                label="Cuenta inteligente"
                onPress={leave('smart_account', money.openSmart)}
              />
            ) : null}
            <Row
              icon="message-circle"
              label="Mensajes"
              // Opens where the unread is: direct messages first, else Julian's channel.
              onPress={leave('messages', () => assistant?.open({ channel: directUnread > 0 ? 'mensajes' : 'julian' }))}
              badge={unreadMessages > 0 ? (unreadMessages > 9 ? '9+' : String(unreadMessages)) : undefined}
            />
          </View>

          {/* ── Apart from the product screens above: inviting (a business
              has no invitations of its own) and the person behind Confío. ── */}
          <View style={[styles.section, styles.sectionApart]}>
            {!isBusiness ? (
              <Row
                icon="gift"
                label="Invitar y ganar"
                onPress={leave('invite', () => (navigationRef as any).navigate('Main', { screen: 'Invite' }))}
              />
            ) : null}
            <Row
              icon="heart"
              label="El fundador"
              onPress={leave('founder', () => (navigationRef as any).navigate('Main', { screen: 'Founder' }))}
            />
          </View>
        </ScrollView>

        {/* ── Profile + account switcher ── */}
        {/* The app's root already keeps every screen above the system bar
            (App.tsx): the foot adds only its own breathing room. */}
        <View style={styles.foot}>
          {/* The other accounts open in place, above the row that names the
              current one: one column of faces and names, part of the menu. */}
          {switching ? (
            <>
              {otherAccounts.length ? <Text style={styles.accountsTitle}>Cambiar a</Text> : null}
              <ScrollView style={styles.accounts} showsVerticalScrollIndicator={false}>
                {otherAccounts.map((account) => (
                  <Pressable
                    key={account.id}
                    onPress={() => {
                      logHomeNav('drawer', 'switch_account');
                      onClose();
                      // The switch (and its progress) is Inicio's: go there first.
                      onGoHome();
                      money.switchAccount(account.id);
                    }}
                    style={({ pressed }) => [styles.person, pressed && styles.pressed]}
                    accessibilityRole="button"
                    accessibilityLabel={`Cambiar a ${account.name}, ${account.kind}`}
                  >
                    <View style={[styles.avatar, styles.avatarOther]}>
                      <Text style={[styles.avatarText, styles.avatarTextOther]}>{account.avatar}</Text>
                    </View>
                    <View style={styles.personText}>
                      <Text style={styles.personName} numberOfLines={1}>{account.name}</Text>
                      <Text style={styles.personKind} numberOfLines={1}>{account.kind}</Text>
                    </View>
                  </Pressable>
                ))}
                <Pressable
                  onPress={() => {
                    logHomeNav('drawer', 'create_business');
                    onClose();
                    money.createBusiness();
                  }}
                  style={({ pressed }) => [styles.person, pressed && styles.pressed]}
                  accessibilityRole="button"
                  accessibilityLabel="Crear cuenta de negocio"
                >
                  <View style={[styles.avatar, styles.avatarAdd]}>
                    <Icon name="plus" size={20} color={EMERALD} />
                  </View>
                  <Text style={styles.personAdd} numberOfLines={1}>Crear cuenta de negocio</Text>
                </Pressable>
              </ScrollView>
              <View style={styles.footRule} />
            </>
          ) : null}
          <View style={styles.footRow}>
            <Pressable
              onPress={leave('profile', () => goTab('Profile'))}
              style={({ pressed }) => [styles.person, styles.personCurrent, pressed && styles.pressed]}
              accessibilityRole="button"
              accessibilityLabel={`Perfil y ajustes de ${accountName}, ${accountKind}`}
            >
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{currentAccountAvatar || accountName.charAt(0).toUpperCase()}</Text>
              </View>
              <View style={styles.personText}>
                <Text style={styles.personName} numberOfLines={1}>{accountName}</Text>
                {/* Says what this row opens: the screen with the person's
                    profile, security and settings. */}
                <View style={styles.personDoor}>
                  <Text style={styles.personDoorText} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.85}>
                    Perfil y ajustes
                  </Text>
                  <Icon name="chevron-right" size={14} color={EMERALD} />
                </View>
              </View>
            </Pressable>
            <Pressable
              onPress={() => setSwitching((open) => !open)}
              style={({ pressed }) => [styles.switch, switching && styles.switchOpen, pressed && styles.pressed]}
              accessibilityRole="button"
              accessibilityState={{ expanded: switching }}
              accessibilityLabel="Cambiar de cuenta"
            >
              <Text style={styles.switchText}>Cambiar</Text>
              <Icon name={switching ? 'chevron-down' : 'chevron-up'} size={16} color={INK} />
            </Pressable>
          </View>
        </View>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  // Above any elevated sibling (the floating Pagar button) on Android.
  overlay: { ...StyleSheet.absoluteFillObject, zIndex: 20, elevation: 20 },
  behind: { flex: 1 },
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(17,24,39,0.45)' },
  panel: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    backgroundColor: '#FFFFFF',
    borderTopRightRadius: 24,
    borderBottomRightRadius: 24,
    shadowColor: '#000',
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 6, height: 0 },
    elevation: 16,
  },
  scroll: { paddingBottom: 12 },
  pressed: { opacity: 0.6 },
  money: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 16 },
  totalRow: { flexDirection: 'row', alignItems: 'flex-end' },
  totalPress: { flex: 1 },
  totalLabel: { fontSize: 13, color: MUTED },
  currency: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    height: 36,
    paddingHorizontal: 10,
    marginBottom: 4,
    borderRadius: 18,
    backgroundColor: '#F3F4F6',
  },
  currencyText: { fontSize: 13, fontWeight: '700', color: INK },
  total: { fontSize: 30, fontWeight: '700', color: INK, marginTop: 2 },
  eye: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  month: { flexDirection: 'row', alignItems: 'center', minHeight: 44, gap: 4 },
  monthText: { flex: 1, fontSize: 14, color: MUTED },
  monthLink: { fontSize: 14, fontWeight: '700', color: EMERALD },
  tilesScroll: { marginHorizontal: -20, marginTop: 4 },
  tiles: { paddingHorizontal: 20, gap: 8 },
  tile: {
    minWidth: 104,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    backgroundColor: '#F3F4F6',
    borderWidth: 1,
    borderColor: '#F3F4F6',
    gap: 2,
  },
  // An offer never looks like a balance: outlined, dashed, no amount.
  tileOffer: { backgroundColor: '#FFFFFF', borderColor: '#6B7280', borderStyle: 'dashed' },
  tilesPending: { flexDirection: 'row' },
  tilePending: { opacity: 0.6 },
  tileLabel: { fontSize: 12, color: MUTED },
  tileAmount: { fontSize: 15, fontWeight: '700', color: INK },
  tileOfferText: { fontSize: 15, fontWeight: '700', color: EMERALD },
  actions: { flexDirection: 'row', gap: 8, marginTop: 14 },
  action: {
    flex: 1,
    height: 46,
    borderRadius: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: '#F3F4F6',
  },
  actionFilled: { backgroundColor: EMERALD },
  actionPressed: { opacity: 0.8 },
  actionText: { fontSize: 15, fontWeight: '700', color: INK },
  actionTextFilled: { color: '#FFFFFF' },
  section: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E5E7EB',
    paddingTop: 8,
    paddingHorizontal: 8,
  },
  sectionApart: { marginTop: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, minHeight: 52, paddingHorizontal: 12, borderRadius: 12 },
  rowLabel: { flex: 1, fontSize: 16, fontWeight: '600', color: INK },
  // Same footprint as a row icon, so the labels stay in one column.
  rowMark: { width: 20, height: 20, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#7C3AED' },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    // violet-600: white 12px bold passes 4.5:1 on it (violet-500 does not).
    backgroundColor: '#7C3AED',
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 12, fontWeight: '700', color: '#FFFFFF' },
  // One column for every face in the foot: 20 from the menu's edge, like
  // the money block and the rows above; names start 12 after the face.
  foot: {
    paddingTop: 8,
    paddingBottom: 12,
    paddingHorizontal: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E5E7EB',
  },
  footRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  footRule: { height: StyleSheet.hairlineWidth, backgroundColor: '#E5E7EB', marginHorizontal: 8, marginVertical: 8 },
  accountsTitle: { fontSize: 13, color: MUTED, paddingHorizontal: 8, paddingTop: 6, paddingBottom: 4 },
  // Four rows and half of the next, so a longer list shows it scrolls.
  accounts: { maxHeight: 252, flexGrow: 0 },
  person: { flexDirection: 'row', alignItems: 'center', gap: 12, height: 56, paddingHorizontal: 8, borderRadius: 12 },
  personCurrent: { flex: 1 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { fontSize: 17, fontWeight: '700', color: '#065F46' },
  // Emerald is the account in use; the others wait in gray.
  avatarOther: { backgroundColor: '#F3F4F6' },
  avatarTextOther: { color: '#374151' },
  avatarAdd: { backgroundColor: '#FFFFFF', borderWidth: 1.5, borderColor: '#A7F3D0', borderStyle: 'dashed' },
  personText: { flex: 1, justifyContent: 'center' },
  personName: { fontSize: 16, fontWeight: '700', color: INK },
  personKind: { fontSize: 13, color: MUTED, marginTop: 1 },
  personDoor: { flexDirection: 'row', alignItems: 'center', gap: 2, marginTop: 1 },
  personDoorText: { flexShrink: 1, fontSize: 13, fontWeight: '700', color: EMERALD },
  personAdd: { flex: 1, fontSize: 16, fontWeight: '700', color: EMERALD },
  switch: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    height: 44,
    // Ends on the menu's 20-point margin, like the rows and buttons above.
    marginRight: 8,
    paddingHorizontal: 12,
    borderRadius: 22,
    backgroundColor: '#F3F4F6',
  },
  switchOpen: { backgroundColor: '#E5E7EB' },
  switchText: { fontSize: 14, fontWeight: '700', color: INK },
});
