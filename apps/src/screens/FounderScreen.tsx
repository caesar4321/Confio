// "El fundador": who is behind Confío, where he writes to the people who
// use it, and where to follow him. Opened from the menu, right under
// "Invitar y ganar" (it used to be a block at the foot of Perfil).
import React from 'react';
import { Image, Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useOptionalAssistant } from '../assistant/AssistantContext';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { logHomeNav } from '../services/homeNavAnalytics';

type Channel = {
  key: string;
  name: string;
  /** What is there, in a few words. */
  what: string;
  url: string;
  image?: number;
};

export const FOUNDER_CHANNELS: Channel[] = [
  { key: 'tiktok', name: 'TikTok', what: '@julianmoonluna', url: 'https://www.tiktok.com/@julianmoonluna',
    image: require('../assets/png/TikTok.png') },
  { key: 'instagram', name: 'Instagram', what: '@julianmoonluna_', url: 'https://www.instagram.com/julianmoonluna_',
    image: require('../assets/png/Instagram.png') },
  { key: 'youtube', name: 'YouTube', what: '@julianmoonluna', url: 'https://www.youtube.com/@julianmoonluna',
    image: require('../assets/png/YouTube.png') },
  { key: 'facebook', name: 'Facebook', what: 'Julian Moon Luna', url: 'https://facebook.com/JulianMoonLuna',
    image: require('../assets/png/Facebook.png') },
  { key: 'whatsapp', name: 'Canal de WhatsApp', what: 'Novedades en tu WhatsApp',
    url: 'https://whatsapp.com/channel/0029Vb8g5GJIiRotAGdWKI1t' },
];

export default function FounderScreen() {
  const navigation = useNavigation();
  const assistant = useOptionalAssistant();
  const open = (channel: Channel) => {
    // Which of his channels people open, counted with the menu's doors.
    logHomeNav('drawer', `founder_${channel.key}`);
    Linking.openURL(channel.url).catch(() => {});
  };
  return (
    <View style={styles.screen}>
      <Header navigation={navigation as any} title="El fundador" backgroundColor={colors.heroField} isLight showBackButton />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <Image source={require('../assets/png/JulianMoon_Founder.jpeg')} style={styles.photo} accessibilityIgnoresInvertColors />
          <Text style={styles.name}>Julian Moon</Text>
          <Text style={styles.handle}>@julianmoonluna · fundador de Confío</Text>
          <Text style={styles.tagline}>Un coreano que sueña con una nueva Latinoamérica</Text>
          <Text style={styles.story}>Descubre por qué un coreano confía en América Latina.</Text>
        </View>

        {/* His own channel inside the app: the closest line to him. */}
        {assistant ? (
          <Pressable
            onPress={() => {
              logHomeNav('drawer', 'founder_messages');
              assistant.open({ channel: 'julian' });
            }}
            style={({ pressed }) => [styles.direct, pressed && styles.directPressed]}
            accessibilityRole="button"
            accessibilityLabel="Mensajes de Julian"
          >
            <View style={styles.directIcon}>
              <Icon name="message-circle" size={20} color={colors.white} />
            </View>
            <View style={styles.rowText}>
              <Text style={styles.directTitle}>Mensajes de Julian</Text>
              <Text style={styles.directSub}>Lo que te escribe, aquí en la app</Text>
            </View>
            <Icon name="chevron-right" size={20} color={colors.white} />
          </Pressable>
        ) : null}

        <Text style={styles.sectionTitle}>Síguelo</Text>
        <View style={styles.card}>
          {FOUNDER_CHANNELS.map((channel, index) => (
            <Pressable
              key={channel.key}
              onPress={() => open(channel)}
              style={({ pressed }) => [styles.row, index > 0 && styles.rowDivider, pressed && styles.rowPressed]}
              accessibilityRole="link"
              accessibilityLabel={`${channel.name} de Julian Moon`}
            >
              <View style={styles.logo}>
                {/* The bubble fills only 86% of the SVG's box (its own shadow
                    margin): 42 draws it the size of the others. */}
                {channel.image
                  ? <Image source={channel.image} style={styles.logoImage} resizeMode="contain" />
                  : <WhatsAppLogo width={42} height={42} />}
              </View>
              <View style={styles.rowText}>
                <Text style={styles.rowTitle}>{channel.name}</Text>
                <Text style={styles.rowSub} numberOfLines={1}>{channel.what}</Text>
              </View>
              <Icon name="arrow-up-right" size={18} color={colors.text.light} />
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  content: { paddingHorizontal: 16, paddingTop: 20, paddingBottom: 28 },
  hero: { alignItems: 'center', paddingHorizontal: 12, marginBottom: 20 },
  photo: { width: 104, height: 104, borderRadius: 52, borderWidth: 3, borderColor: colors.white, backgroundColor: '#E5E7EB' },
  name: { fontSize: 22, fontWeight: '700', color: colors.text.primary, marginTop: 12 },
  handle: { fontSize: 14, color: colors.text.secondary, marginTop: 2 },
  tagline: { fontSize: 17, lineHeight: 24, fontWeight: '600', color: colors.text.primary, textAlign: 'center', marginTop: 14 },
  story: { fontSize: 15, lineHeight: 22, color: colors.text.secondary, textAlign: 'center', marginTop: 6 },
  direct: {
    flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 64, paddingHorizontal: 14, borderRadius: 16,
    backgroundColor: '#047857',
  },
  directPressed: { backgroundColor: '#065F46' },
  directIcon: {
    width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.16)',
  },
  directTitle: { fontSize: 16, fontWeight: '700', color: colors.white },
  directSub: { fontSize: 13, color: '#D1FAE5', marginTop: 2 },
  sectionTitle: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginTop: 24, marginBottom: 8, marginLeft: 4 },
  card: { borderRadius: 16, backgroundColor: colors.white, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 64, paddingHorizontal: 14 },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#E5E7EB' },
  rowPressed: { backgroundColor: '#F3F4F6' },
  logo: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  logoImage: { width: 36, height: 36 },
  rowText: { flex: 1 },
  rowTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
  rowSub: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
});
