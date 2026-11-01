// The first meeting: once ever, the person's own pet greets them across the
// whole screen. When they answer, the pet shrinks into its corner and the
// conversation carries on in a speech bubble over the real Inicio.
import React, { useEffect, useRef, useState } from 'react';
import { Animated, BackHandler, Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import AssistantMascot from './AssistantMascot';
import type { AssistantGuide, AssistantGuideChip, AssistantProfile } from './api';

const PET_SIZE = 120;
const TALK_MS = 2500;
const PET_TOP = 56;
const APPEAR_MS = 260;

type Props = {
  guide: AssistantGuide;
  profile?: AssistantProfile | null;
  // 0 full screen, 1 the pet has landed where the speech bubble's pet sits.
  collapse: Animated.Value;
  landing: { x: number; y: number; size: number };
  leaving: boolean;
  chips: AssistantGuideChip[];
  onChip: (chip: AssistantGuideChip) => void;
};

export default function GuideOpening({ guide, profile, collapse, landing, leaving, chips, onChip }: Props) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const appear = useRef(new Animated.Value(0)).current;
  // Talking redraws the window: a greeting's worth, then it rests.
  const [talking, setTalking] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setTalking(false), TALK_MS);
    return () => clearTimeout(timer);
  }, []);
  const dismiss = chips.find((c) => c.kind === 'dismiss');
  const answers = chips.filter((c) => c.kind !== 'dismiss');

  useEffect(() => {
    Animated.timing(appear, { toValue: 1, duration: APPEAR_MS, useNativeDriver: true }).start();
  }, [appear]);

  // Android's back means "not now", never leaving the app behind this screen.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (dismiss && !leaving) {
        onChip(dismiss);
      }
      return true;
    });
    return () => sub.remove();
  }, [dismiss, leaving, onChip]);

  const startX = width / 2;
  const startY = insets.top + PET_TOP + PET_SIZE / 2;
  const fadeOut = collapse.interpolate({ inputRange: [0, 0.5], outputRange: [1, 0], extrapolate: 'clamp' });
  const backdrop = collapse.interpolate({ inputRange: [0, 0.8], outputRange: [1, 0], extrapolate: 'clamp' });

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={leaving ? 'none' : 'auto'}>
      <Animated.View style={[StyleSheet.absoluteFill, styles.backdrop, { opacity: Animated.multiply(appear, backdrop) }]} />
      <Animated.View style={[styles.fill, { opacity: Animated.multiply(appear, fadeOut) }]}>
        <ScrollView
          contentContainerStyle={[styles.content, { paddingTop: insets.top + PET_TOP + PET_SIZE + 20, paddingBottom: insets.bottom + 16 }]}
          showsVerticalScrollIndicator={false}
        >
        <Text style={styles.text}>{guide.text}</Text>
        <View style={styles.answers}>
          {answers.map((chip) => (
            <Pressable
              key={chip.label}
              onPress={() => onChip(chip)}
              accessibilityRole="button"
              style={({ pressed }) => [styles.answer, pressed && styles.pressed]}
            >
              <Text style={styles.answerText}>{chip.label}</Text>
              <Icon name="chevron-right" size={18} color={colors.text.light} />
            </Pressable>
          ))}
        </View>
        {dismiss ? (
          <Pressable onPress={() => onChip(dismiss)} hitSlop={10} accessibilityRole="button" style={styles.later}>
            <Text style={styles.laterText}>{dismiss.label}</Text>
          </Pressable>
        ) : null}
        </ScrollView>
      </Animated.View>
      <Animated.View
        pointerEvents="none"
        style={[styles.pet, {
          left: startX - PET_SIZE / 2,
          top: startY - PET_SIZE / 2,
          opacity: appear,
          transform: [
            { translateX: collapse.interpolate({ inputRange: [0, 1], outputRange: [0, landing.x - startX] }) },
            { translateY: collapse.interpolate({ inputRange: [0, 1], outputRange: [0, landing.y - startY] }) },
            { scale: collapse.interpolate({ inputRange: [0, 1], outputRange: [1, landing.size / PET_SIZE] }) },
          ],
        }]}
      >
        <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
          size={PET_SIZE} mood={talking ? 'talking' : 'idle'} />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  // Pale on purpose: the pet is often this green, and any pet color must stand out.
  backdrop: { backgroundColor: colors.primarySoft },
  fill: { flex: 1 },
  content: { paddingHorizontal: 20 },
  text: { fontSize: 22, lineHeight: 29, fontWeight: '700', color: colors.text.primary, textAlign: 'center' },
  answers: { gap: 8, marginTop: 22 },
  answer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 50,
    paddingHorizontal: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.white,
  },
  pressed: { opacity: 0.8 },
  answerText: { flex: 1, fontSize: 15, color: colors.text.primary },
  later: { alignSelf: 'center', marginTop: 16, padding: 6 },
  laterText: { fontSize: 15, color: colors.text.secondary },
  pet: { position: 'absolute', width: PET_SIZE, height: PET_SIZE, alignItems: 'center', justifyContent: 'center' },
});
