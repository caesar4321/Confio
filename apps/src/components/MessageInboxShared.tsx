import React from 'react';
import { Image, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/FontAwesome';

import CONFIOLogo from '../assets/png/CONFIO.png';
import founderImage from '../assets/png/JulianMoon_Founder.jpeg';

export const tealGreen = '#34d399';
export const tealLight = '#E8F8F2';
export const messageReactionOptions = ['🔥', '🙌', '😍', '🤯', '💡', '😎', '💪', '👀', '😢', '❤️'] as const;

export type MessageReactionSummary = {
  emoji: string;
  count: number;
};

export type VideoMessage = {
  id: number;
  type: 'video';
  isPinned?: boolean;
  occurredAt?: string;
  platform: string;
  platforms?: Array<'TikTok' | 'Instagram' | 'YouTube'>;
  platformLinks?: Array<{
    platform: 'TikTok' | 'Instagram' | 'YouTube';
    url: string;
  }>;
  reactionSummary?: MessageReactionSummary[];
  viewerReaction?: string | null;
  canReact?: boolean;
  title: string;
  time: string;
  imageUrl?: string;
};

export type TextMessage = {
  id: number;
  type: 'text';
  isPinned?: boolean;
  occurredAt?: string;
  tag?: string;
  reactionSummary?: MessageReactionSummary[];
  viewerReaction?: string | null;
  canReact?: boolean;
  text: string;
  time: string;
  imageUrl?: string;
};

export type NewsMessage = {
  id: number;
  type: 'news';
  isPinned?: boolean;
  occurredAt?: string;
  reactionSummary?: MessageReactionSummary[];
  viewerReaction?: string | null;
  canReact?: boolean;
  tag: string;
  title: string;
  body: string;
  time: string;
  imageUrl?: string;
};

export type SupportMessage = {
  id: number;
  type: 'support';
  isPinned?: boolean;
  occurredAt?: string;
  reactionSummary?: MessageReactionSummary[];
  viewerReaction?: string | null;
  canReact?: boolean;
  senderType?: 'USER' | 'AGENT' | 'SYSTEM' | null;
  senderName?: string | null;
  text: string;
  time: string;
};

export type ChannelMessage = VideoMessage | TextMessage | NewsMessage | SupportMessage;

export type Channel = {
  id: 'julian' | 'confio' | 'soporte';
  serverId: string;
  name: string;
  subtitle: string;
  preview: string;
  time: string;
  isMuted?: boolean;
  messages: ChannelMessage[];
};

export type ScreenState = 'inbox' | 'channel';

export const channelMeta: Record<
  Channel['id'],
  {
    badge: string;
    badgeBackground: string;
    badgeColor: string;
    avatarBackground: string;
    description: string;
  }
> = {
  julian: {
    badge: 'Founder',
    badgeBackground: '#EEF2FF',
    badgeColor: '#4F46E5',
    avatarBackground: '#EEF2FF',
    description: 'Mensajes directos del fundador',
  },
  confio: {
    badge: 'Novedades',
    badgeBackground: '#E8F8F2',
    badgeColor: '#0F9F74',
    avatarBackground: tealLight,
    description: 'Lanzamientos y cambios del producto',
  },
  soporte: {
    badge: 'Oficial',
    badgeBackground: '#FFF4E5',
    badgeColor: '#C26B00',
    avatarBackground: '#FFF7ED',
    description: 'Ayuda y respuestas del equipo',
  },
};

export const messageChannels: Channel[] = [
  {
    id: 'julian',
    serverId: 'julian',
    name: '🇰🇷 Julian Moon 🌙',
    subtitle: '@julianmoonluna',
    preview: 'Argentina tiene uno de los Big Mac mas caros...',
    time: '9h',
    isMuted: false,
    messages: [
      {
        id: 1,
        type: 'video',
        platform: 'TikTok',
        platforms: ['TikTok'],
        platformLinks: [{ platform: 'TikTok', url: 'https://vt.tiktok.com/ZSuh2oDTr/' }],
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        title: 'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.',
        time: 'Hace 9h',
      },
      {
        id: 2,
        type: 'video',
        platform: 'TikTok + Instagram',
        platforms: ['TikTok', 'Instagram', 'YouTube'],
        platformLinks: [],
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        title: 'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real',
        time: 'Hace 1 dia',
      },
      {
        id: 3,
        type: 'text',
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        text: 'Estamos a punto de cerrar el trato con los bancos locales. Vienen en 2-4 semanas.',
        time: 'Hace 3 dias',
      },
    ],
  },
  {
    id: 'confio',
    serverId: 'confio-news',
    name: 'Confío News',
    subtitle: 'Novedades del producto',
    preview: 'Integracion Koywe completada para AR, BO...',
    time: '2h',
    isMuted: false,
    messages: [
      {
        id: 1,
        type: 'news',
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        tag: 'Producto',
        title: 'Integracion Koywe completada',
        body: 'On/off-ramp confirmado para Argentina, Bolivia, Colombia, Mexico y Peru. El retiro a cuenta bancaria llega en 2-4 semanas.',
        time: 'Hace 2h',
      },
      {
        id: 2,
        type: 'news',
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        tag: 'KYC',
        title: 'Confío x Didit: verificación en tiempo real',
        body: 'Verifica tu identidad en menos de 60 segundos. Sin papeles, sin esperas.',
        time: 'Hace 1 dia',
      },
      {
        id: 3,
        type: 'news',
        reactionSummary: [],
        viewerReaction: null,
        canReact: true,
        tag: 'Preventa',
        title: 'Fase 1-1 activa: $CONFIO a $0.20',
        body: 'La primera fase de preventa esta abierta. Se parte de los primeros 10,000 usuarios fundadores.',
        time: 'Hace 5 dias',
      },
    ],
  },
  {
    id: 'soporte',
    serverId: 'soporte',
    name: 'Soporte',
    subtitle: 'Equipo Confío · Respuesta en ~2h',
    preview: 'En que podemos ayudarte hoy?',
    time: 'Ahora',
    isMuted: false,
    messages: [
      {
        id: 1,
        type: 'support',
        reactionSummary: [],
        viewerReaction: null,
        canReact: false,
        text: 'Hola, somos el equipo de Confío. ¿En qué podemos ayudarte hoy?',
        time: 'Ahora',
      },
    ],
  },
];

type ChannelAvatarProps = {
  channel: Channel;
  large?: boolean;
};

export function ChannelAvatar({ channel, large = false }: ChannelAvatarProps) {
  const containerStyle = large ? styles.channelHeaderAvatar : styles.channelAvatar;
  const imageStyle = large ? styles.channelHeaderAvatarImage : styles.channelAvatarImage;

  if (channel.id === 'julian') {
    return (
      <View style={[containerStyle, styles.avatarImageContainer]}>
        <Image source={founderImage} style={imageStyle} />
      </View>
    );
  }

  if (channel.id === 'confio') {
    return (
      <View style={[containerStyle, styles.confioAvatarContainer]}>
        <Image source={CONFIOLogo} style={imageStyle} resizeMode="cover" />
      </View>
    );
  }

  return (
    <View style={[containerStyle, styles.supportAvatarBadge]}>
      <Icon name="headphones" size={large ? 16 : 18} color="#0F9F74" />
    </View>
  );
}

const styles = StyleSheet.create({
  channelAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  channelHeaderAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarImageContainer: {
    overflow: 'hidden',
    backgroundColor: '#FFFFFF',
  },
  channelAvatarImage: {
    width: 48,
    height: 48,
    borderRadius: 24,
  },
  channelHeaderAvatarImage: {
    width: 36,
    height: 36,
    borderRadius: 18,
  },
  confioAvatarContainer: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E8EEF2',
    overflow: 'hidden',
  },
  supportAvatarBadge: {
    backgroundColor: '#ECFDF3',
    borderWidth: 1,
    borderColor: '#D1FADF',
  },
});
