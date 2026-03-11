import React, { useMemo, useState } from 'react';
import {
  Image,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import FAIcon from 'react-native-vector-icons/FontAwesome';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

const tealGreen = '#34d399';
const tealLight = '#E8F8F2';

type VideoMessage = {
  id: number;
  type: 'video';
  platform: string;
  platforms?: Array<'TikTok' | 'Instagram' | 'YouTube'>;
  title: string;
  time: string;
  link: string;
};

type TextMessage = {
  id: number;
  type: 'text';
  text: string;
  time: string;
};

type NewsMessage = {
  id: number;
  type: 'news';
  tag: string;
  title: string;
  body: string;
  time: string;
};

type SupportMessage = {
  id: number;
  type: 'support';
  text: string;
  time: string;
};

type ChannelMessage = VideoMessage | TextMessage | NewsMessage | SupportMessage;

type Channel = {
  id: 'julian' | 'confio' | 'soporte';
  avatar: string;
  name: string;
  subtitle: string;
  preview: string;
  time: string;
  unread: number;
  messages: ChannelMessage[];
};

type ScreenState = 'home' | 'inbox' | 'channel';

const messageChannels: Channel[] = [
  {
    id: 'julian',
    avatar: '🇰🇷',
    name: 'Julian Moon',
    subtitle: 'Founder · @julianmoonluna',
    preview: 'Argentina tiene uno de los Big Mac mas caros...',
    time: '9h',
    unread: 3,
    messages: [
      {
        id: 1,
        type: 'video',
        platform: 'TikTok',
        platforms: ['TikTok'],
        title: 'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.',
        time: 'Hace 9h',
        link: 'https://vt.tiktok.com/ZSuh2oDTr/',
      },
      {
        id: 2,
        type: 'video',
        platform: 'TikTok + Instagram',
        platforms: ['TikTok', 'Instagram', 'YouTube'],
        title: 'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real',
        time: 'Hace 1 dia',
        link: '#',
      },
      {
        id: 3,
        type: 'text',
        text: 'Estamos a punto de cerrar el trato con los bancos locales. Vienen en 2-4 semanas.',
        time: 'Hace 3 dias',
      },
    ],
  },
  {
    id: 'confio',
    avatar: '💚',
    name: 'Confío News',
    subtitle: 'Novedades del producto',
    preview: 'Integracion Koywe completada para AR, BO...',
    time: '2h',
    unread: 1,
    messages: [
      {
        id: 1,
        type: 'news',
        tag: 'Producto',
        title: 'Integracion Koywe completada',
        body: 'On/off-ramp confirmado para Argentina, Bolivia, Colombia, Mexico y Peru. El retiro a cuenta bancaria llega en 2-4 semanas.',
        time: 'Hace 2h',
      },
      {
        id: 2,
        type: 'news',
        tag: 'KYC',
        title: 'Confío x Didit: verificación en tiempo real',
        body: 'Verifica tu identidad en menos de 60 segundos. Sin papeles, sin esperas.',
        time: 'Hace 1 dia',
      },
      {
        id: 3,
        type: 'news',
        tag: 'Preventa',
        title: 'Fase 1-1 activa: $CONFIO a $0.20',
        body: 'La primera fase de preventa esta abierta. Se parte de los primeros 10,000 usuarios fundadores.',
        time: 'Hace 5 dias',
      },
    ],
  },
  {
    id: 'soporte',
    avatar: '🎧',
    name: 'Soporte',
    subtitle: 'Equipo Confío · Respuesta en ~2h',
    preview: 'En que podemos ayudarte hoy?',
    time: 'Ahora',
    unread: 0,
    messages: [
      {
        id: 1,
        type: 'support',
        text: 'Hola, somos el equipo de Confío. ¿En qué podemos ayudarte hoy?',
        time: 'Ahora',
      },
    ],
  },
];

const quickActions = [
  { id: 'send', icon: 'send', label: 'Enviar', color: tealGreen },
  { id: 'pay', icon: 'shopping-bag', label: 'Pagar', color: '#7C3AED' },
  { id: 'exchange', icon: 'dollar-sign', label: 'Recargar', color: '#2563EB' },
  { id: 'withdraw', icon: 'bank', label: 'Retirar', color: '#F59E0B', isFA: true },
];

const platformButtonStyles: Record<'TikTok' | 'Instagram' | 'YouTube', { bg: string; fg: string }> = {
  TikTok: { bg: '#111111', fg: '#FFFFFF' },
  Instagram: { bg: '#C13584', fg: '#FFFFFF' },
  YouTube: { bg: '#DC2626', fg: '#FFFFFF' },
};

export default function HomeMockUpScreen() {
  const [screen, setScreen] = useState<ScreenState>('home');
  const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
  const [unreadCounts, setUnreadCounts] = useState<Record<Channel['id'], number>>({
    julian: 3,
    confio: 1,
    soporte: 0,
  });

  const totalUnread = useMemo(
    () => Object.values(unreadCounts).reduce((sum, count) => sum + count, 0),
    [unreadCounts]
  );

  const openChannel = (channel: Channel) => {
    setActiveChannel(channel);
    setUnreadCounts((prev) => ({ ...prev, [channel.id]: 0 }));
    setScreen('channel');
  };

  const openLink = async (link: string) => {
    if (!link || link === '#') {
      return;
    }

    try {
      await Linking.openURL(link);
    } catch (error) {
      console.warn('Failed to open link', error);
    }
  };

  if (screen === 'home') {
    return (
      <View style={styles.container}>
        <SafeAreaView edges={['top']} style={styles.balanceCard}>
          <View style={styles.homeHeaderInner}>
            <View style={styles.portfolioHeader}>
              <View style={styles.portfolioTitleContainer}>
                <Text style={styles.brand}>Confío</Text>
              </View>
              <View style={styles.portfolioActions}>
                <Pressable style={styles.iconBubble}>
                  <Icon name="bell" size={20} color="#FFFFFF" />
                  <View style={styles.redDot} />
                </Pressable>

                <Pressable style={styles.iconBubble} onPress={() => setScreen('inbox')}>
                  <Icon name="message-circle" size={19} color="#FFFFFF" />
                  <View style={styles.redDot} />
                  {totalUnread > 0 && (
                    <View style={styles.unreadBadge}>
                      <Text style={styles.unreadBadgeText}>{totalUnread}</Text>
                    </View>
                  )}
                </Pressable>

                <View style={styles.avatarCircle}>
                  <Text style={styles.avatarText}>J</Text>
                </View>
              </View>
            </View>

            <Text style={styles.portfolioLabel}>Mi Saldo Total</Text>
            <Text style={styles.portfolioSubLabel}>En Dólares</Text>
            <View style={styles.balanceRow}>
              <Text style={styles.currencySymbol}>$</Text>
              <Text style={styles.balanceAmount}>16.00</Text>
            </View>
          </View>
        </SafeAreaView>

        <ScrollView contentContainerStyle={styles.homeContent}>
          <View style={styles.quickActionsCard}>
              {quickActions.map((action) => (
                <View key={action.label} style={styles.actionButton}>
                  <View style={[styles.actionIcon, { backgroundColor: action.color }]}>
                    {action.isFA ? (
                      <FAIcon name={action.icon} size={20} color="#FFFFFF" />
                    ) : (
                      <Icon name={action.icon} size={20} color="#FFFFFF" />
                    )}
                  </View>
                  <Text style={styles.actionLabel}>{action.label}</Text>
                </View>
              ))}
          </View>

          <View style={styles.walletsSection}>
            <Text style={styles.sectionTitle}>Mis Billeteras</Text>
            <View style={styles.walletCard}>
              <View style={styles.walletCardContent}>
                <View style={[styles.walletLogoContainer, { backgroundColor: '#FFFFFF' }]}>
                  <Image source={cUSDLogo} style={styles.walletLogo} />
                </View>
                <View style={styles.walletInfo}>
                  <Text style={styles.walletName}>Confío Dollar</Text>
                  <Text style={styles.walletTicker}>cUSD</Text>
                </View>
                <View style={styles.walletBalanceContainer}>
                  <Text style={styles.walletAmount}>$1.02</Text>
                  <Icon name="chevron-right" size={20} color="#9CA3AF" />
                </View>
              </View>
            </View>

            <View style={styles.walletCard}>
              <View style={styles.walletCardContent}>
                <View style={[styles.walletLogoContainer, styles.confioWalletLogoContainer]}>
                  <Image source={CONFIOLogo} style={styles.walletLogo} />
                </View>
                <View style={styles.walletInfo}>
                  <Text style={styles.walletName}>Confío</Text>
                  <Text style={styles.walletTicker}>CONFIO</Text>
                </View>
                <View style={styles.walletBalanceContainer}>
                  <Text style={styles.walletAmount}>80.00</Text>
                  <Icon name="chevron-right" size={20} color="#9CA3AF" />
                </View>
              </View>
            </View>
          </View>
        </ScrollView>
      </View>
    );
  }

  if (screen === 'inbox') {
    return (
      <View style={styles.container}>
        <SafeAreaView edges={['top']} style={styles.secondaryHeaderSafe}>
          <View style={styles.secondaryHeader}>
            <Pressable onPress={() => setScreen('home')} style={styles.backButton}>
              <Icon name="arrow-left" size={22} color="#1F2937" />
            </Pressable>
            <View style={styles.secondaryHeaderCopy}>
              <Text style={styles.secondaryHeaderTitle}>Mensajes</Text>
              <Text style={styles.secondaryHeaderSubtitle}>Actualizaciones, fundador y soporte</Text>
            </View>
          </View>
        </SafeAreaView>

        <ScrollView contentContainerStyle={styles.secondaryContent}>
          <View style={styles.inboxHero}>
            <View style={styles.inboxHeroIcon}>
              <Icon name="message-circle" size={18} color={tealGreen} />
            </View>
            <View style={styles.inboxHeroCopy}>
              <Text style={styles.inboxHeroTitle}>Bandeja prioritaria</Text>
              <Text style={styles.inboxHeroBody}>
                Recibe noticias del producto, mensajes del founder y respuestas del equipo.
              </Text>
            </View>
          </View>

          <View style={styles.channelList}>
            {messageChannels.map((channel) => {
              const unread = unreadCounts[channel.id];
              return (
                <Pressable
                  key={channel.id}
                  onPress={() => openChannel(channel)}
                  style={[styles.channelCard, unread > 0 && styles.channelCardUnread]}
                >
                  <View style={styles.channelAvatar}>
                    <Text style={styles.channelAvatarText}>{channel.avatar}</Text>
                  </View>

                  <View style={styles.channelBody}>
                    <View style={styles.channelTopRow}>
                      <Text style={styles.channelName}>{channel.name}</Text>
                      <Text style={styles.channelTime}>{channel.time}</Text>
                    </View>
                    <Text style={styles.channelSubtitle}>{channel.subtitle}</Text>
                    <Text style={styles.channelPreview} numberOfLines={1}>
                      {channel.preview}
                    </Text>
                  </View>

                  <View style={styles.channelTrailing}>
                    {unread > 0 ? (
                      <View style={styles.channelUnreadBadge}>
                        <Text style={styles.channelUnreadText}>{unread}</Text>
                      </View>
                    ) : (
                      <View style={styles.channelSeenDot} />
                    )}
                    <Icon name="chevron-right" size={16} color="#C7CDD4" />
                  </View>
                </Pressable>
              );
            })}
          </View>
        </ScrollView>
      </View>
    );
  }

  if (!activeChannel) {
    return null;
  }

  return (
    <View style={styles.container}>
      <SafeAreaView edges={['top']} style={styles.secondaryHeaderSafe}>
        <View style={styles.secondaryHeader}>
          <Pressable onPress={() => setScreen('inbox')} style={styles.backButton}>
            <Icon name="arrow-left" size={22} color="#1F2937" />
          </Pressable>

          <View style={styles.channelHeaderAvatar}>
            <Text style={styles.channelHeaderAvatarText}>{activeChannel.avatar}</Text>
          </View>

          <View>
            <Text style={styles.channelHeaderName}>{activeChannel.name}</Text>
            <Text style={styles.channelHeaderSubtitle}>{activeChannel.subtitle}</Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.secondaryContent}>
        <View style={styles.messagesWrap}>
          {activeChannel.messages.map((message) => (
            <View key={message.id} style={styles.messageCard}>
              {message.type === 'video' && (
                <>
                  <View style={styles.messageMetaRow}>
                    <View style={[styles.messageTag, styles.videoTag]}>
                      <Text style={[styles.messageTagText, styles.videoTagText]}>
                        ▶ Video
                      </Text>
                    </View>
                    <Text style={styles.messageTime}>{message.time}</Text>
                  </View>
                  <Text style={styles.videoTitle}>{message.title}</Text>
                  <View style={styles.videoPlatformsRow}>
                    {(message.platforms || [message.platform as 'TikTok' | 'Instagram' | 'YouTube']).map((platform) => (
                      <Pressable
                        key={platform}
                        onPress={() => openLink(message.link)}
                        style={[
                          styles.videoPlatformButton,
                          { backgroundColor: platformButtonStyles[platform].bg },
                        ]}
                      >
                        <View style={styles.videoPlatformButtonInner}>
                          <Text
                            style={[
                              styles.videoPlatformButtonText,
                              { color: platformButtonStyles[platform].fg },
                            ]}
                          >
                            {platform}
                          </Text>
                          <Icon
                            name="external-link"
                            size={12}
                            color={platformButtonStyles[platform].fg}
                          />
                        </View>
                      </Pressable>
                    ))}
                  </View>
                </>
              )}

              {message.type === 'text' && (
                <View style={styles.textMessageRow}>
                  <Text style={styles.textMessageBody}>{message.text}</Text>
                  <Text style={styles.messageTime}>{message.time}</Text>
                </View>
              )}

              {message.type === 'news' && (
                <>
                  <View style={styles.messageMetaRow}>
                    <View style={[styles.messageTag, styles.newsTag]}>
                      <Text style={[styles.messageTagText, styles.newsTagText]}>
                        {message.tag}
                      </Text>
                    </View>
                    <Text style={styles.messageTime}>{message.time}</Text>
                  </View>
                  <Text style={styles.newsTitle}>{message.title}</Text>
                  <Text style={styles.newsBody}>{message.body}</Text>
                </>
              )}

              {message.type === 'support' && (
                <View style={styles.supportRow}>
                  <View style={styles.supportAvatar}>
                    <Text style={styles.supportAvatarText}>🎧</Text>
                  </View>
                  <View style={styles.supportBubble}>
                    <Text style={styles.supportText}>{message.text}</Text>
                  </View>
                </View>
              )}
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  homeContent: {
    paddingBottom: 100,
  },
  balanceCard: {
    backgroundColor: tealGreen,
    paddingTop: 20,
    paddingBottom: 30,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  homeHeaderInner: {
    paddingTop: Platform.OS === 'ios' ? 0 : StatusBar.currentHeight || 0,
  },
  portfolioHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  portfolioTitleContainer: {
    flex: 1,
  },
  brand: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: '700',
  },
  portfolioActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  iconBubble: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: 'rgba(255,255,255,0.20)',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  redDot: {
    position: 'absolute',
    top: -1,
    right: -1,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#FF4444',
  },
  unreadBadge: {
    position: 'absolute',
    top: -2,
    right: -2,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#FF4444',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  unreadBadgeText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: '700',
  },
  avatarCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: tealGreen,
    fontSize: 16,
    fontWeight: '700',
  },
  portfolioLabel: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.95)',
    fontWeight: '500',
  },
  portfolioSubLabel: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.7)',
    marginTop: 2,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginBottom: 12,
  },
  currencySymbol: {
    fontSize: 24,
    color: '#FFFFFF',
    marginRight: 6,
    fontWeight: '500',
  },
  balanceAmount: {
    fontSize: 42,
    fontWeight: '700',
    color: '#FFFFFF',
    letterSpacing: -1,
  },
  quickActionsCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    paddingVertical: 24,
    paddingHorizontal: 16,
    marginHorizontal: 20,
    marginTop: -8,
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 5,
  },
  actionButton: {
    alignItems: 'center',
    flex: 1,
  },
  actionIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  actionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
  },
  walletsSection: {
    paddingHorizontal: 20,
    marginTop: 28,
  },
  sectionTitle: {
    marginBottom: 16,
    fontSize: 20,
    fontWeight: 'bold',
    color: '#111111',
  },
  walletCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    marginBottom: 12,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 6,
    elevation: 2,
  },
  walletCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
  },
  walletLogoContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  walletLogo: {
    width: 44,
    height: 44,
    borderRadius: 22,
  },
  confioWalletLogoContainer: {
    backgroundColor: '#8B5CF6',
  },
  walletName: {
    fontSize: 17,
    fontWeight: '600',
    color: '#111111',
  },
  walletTicker: {
    fontSize: 14,
    color: '#6B7280',
    marginTop: 2,
  },
  walletInfo: {
    flex: 1,
  },
  walletBalanceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletAmount: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111111',
    marginRight: 8,
  },
  secondaryContent: {
    paddingBottom: 28,
  },
  secondaryHeaderSafe: {
    backgroundColor: '#FFFFFF',
  },
  secondaryHeader: {
    backgroundColor: '#FFFFFF',
    paddingHorizontal: 16,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#EAEAEA',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  backButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#F9FAFB',
  },
  secondaryHeaderCopy: {
    flex: 1,
  },
  secondaryHeaderTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111111',
  },
  secondaryHeaderSubtitle: {
    marginTop: 2,
    fontSize: 12,
    color: '#8A94A6',
  },
  inboxHero: {
    marginHorizontal: 14,
    marginTop: 12,
    marginBottom: 4,
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E8EEF2',
  },
  inboxHeroIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: tealLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  inboxHeroCopy: {
    flex: 1,
  },
  inboxHeroTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#111827',
  },
  inboxHeroBody: {
    marginTop: 3,
    fontSize: 12,
    lineHeight: 17,
    color: '#667085',
  },
  channelList: {
    paddingHorizontal: 14,
    paddingTop: 12,
  },
  channelCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
    borderWidth: 1,
    borderColor: '#EEF2F6',
  },
  channelCardUnread: {
    borderColor: '#D9F4EA',
    backgroundColor: '#FCFEFD',
  },
  channelAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: tealLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  channelAvatarText: {
    fontSize: 22,
  },
  channelBody: {
    flex: 1,
  },
  channelTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 3,
  },
  channelName: {
    fontSize: 14,
    fontWeight: '700',
    color: '#111111',
  },
  channelSubtitle: {
    fontSize: 11,
    color: tealGreen,
    fontWeight: '600',
    marginBottom: 4,
  },
  channelTime: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  channelPreview: {
    fontSize: 12,
    color: '#667085',
  },
  channelTrailing: {
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 10,
    gap: 8,
  },
  channelSeenDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#D0D5DD',
  },
  channelUnreadBadge: {
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: tealGreen,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
    marginLeft: 8,
  },
  channelUnreadText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  channelHeaderAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: tealLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  channelHeaderAvatarText: {
    fontSize: 18,
  },
  channelHeaderName: {
    fontSize: 14,
    fontWeight: '700',
    color: '#111111',
  },
  channelHeaderSubtitle: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  messagesWrap: {
    paddingHorizontal: 14,
    paddingTop: 14,
  },
  messageCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 14,
    marginBottom: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
  },
  messageMetaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  messageTag: {
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  messageTagText: {
    fontSize: 11,
    fontWeight: '700',
  },
  videoTag: {
    backgroundColor: '#FF444418',
  },
  videoTagText: {
    color: '#FF4444',
  },
  newsTag: {
    backgroundColor: tealLight,
  },
  newsTagText: {
    color: tealGreen,
  },
  messageTime: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  videoTitle: {
    marginBottom: 10,
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
    color: '#111111',
  },
  videoPlatformsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  videoPlatformButton: {
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  videoPlatformButtonInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  videoPlatformButtonText: {
    fontSize: 12,
    fontWeight: '600',
  },
  textMessageRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 8,
  },
  textMessageBody: {
    flex: 1,
    fontSize: 13,
    lineHeight: 20,
    color: '#333333',
  },
  newsTitle: {
    marginBottom: 5,
    fontSize: 14,
    fontWeight: '700',
    color: '#111111',
  },
  newsBody: {
    fontSize: 13,
    lineHeight: 20,
    color: '#555555',
  },
  supportRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  supportAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: tealLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  supportAvatarText: {
    fontSize: 16,
  },
  supportBubble: {
    flex: 1,
    backgroundColor: '#F4F6F8',
    borderTopLeftRadius: 4,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  supportText: {
    fontSize: 13,
    lineHeight: 20,
    color: '#333333',
  },
});
