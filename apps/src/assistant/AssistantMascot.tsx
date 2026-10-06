// Confio Assistant's face: Confi (the default) or the pet the user picked.
// Drawn in SVG on a 100x100 canvas so it stays crisp from the 56pt bubble
// to the picker; the body color is the user's choice, features stay fixed.
import React, { useEffect, useState } from 'react';
import { Image, View } from 'react-native';
import Svg, { Circle, Ellipse, G, Path, Rect } from 'react-native-svg';
import Animated, {
  Easing,
  cancelAnimation,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';

export type MascotKind = 'CONFI' | 'LLAMA' | 'CAPYBARA' | 'CAT' | 'DOG' | 'CUSTOM';
export type MascotMood = 'idle' | 'thinking' | 'talking' | 'listening' | 'happy';

export const MASCOTS: { kind: MascotKind; label: string; color: string }[] = [
  { kind: 'CONFI', label: 'Confi', color: '#10B981' },
  { kind: 'LLAMA', label: 'Llama', color: '#F5E6D3' },
  { kind: 'CAPYBARA', label: 'Capibara', color: '#B07A4F' },
  { kind: 'CAT', label: 'Gato', color: '#F59E0B' },
  { kind: 'DOG', label: 'Perro', color: '#A16207' },
];

export const MASCOT_COLORS = ['#10B981', '#047857', '#F59E0B', '#B07A4F', '#F5E6D3', '#8B5CF6', '#3B82F6', '#F472B6', '#374151'];

const INK = '#1F2937';

export function defaultMascotColor(kind: MascotKind) {
  return MASCOTS.find((m) => m.kind === kind)?.color ?? '#10B981';
}

function shade(hex: string, amount: number) {
  const n = parseInt(hex.slice(1), 16);
  const clamp = (v: number) => Math.max(0, Math.min(255, v));
  const r = clamp((n >> 16) + amount);
  const g = clamp(((n >> 8) & 0xff) + amount);
  const b = clamp((n & 0xff) + amount);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

function isLight(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 0xff) + 0.114 * (n & 0xff) > 170;
}

function Eyes({ y, spread = 13, closed, mood }: { y: number; spread?: number; closed: boolean; mood: MascotMood }) {
  if (closed || mood === 'happy') {
    const d = (cx: number) => `M${cx - 5} ${y} Q${cx} ${y - 5} ${cx + 5} ${y}`;
    return (
      <G stroke={INK} strokeWidth={3} strokeLinecap="round" fill="none">
        <Path d={d(50 - spread)} />
        <Path d={d(50 + spread)} />
      </G>
    );
  }
  const look = mood === 'thinking' ? -2 : 0;
  return (
    <G>
      <Ellipse cx={50 - spread} cy={y} rx={4.5} ry={5.5} fill={INK} />
      <Ellipse cx={50 + spread} cy={y} rx={4.5} ry={5.5} fill={INK} />
      <Circle cx={50 - spread + 1.5} cy={y - 2 + look} r={1.6} fill="#FFFFFF" />
      <Circle cx={50 + spread + 1.5} cy={y - 2 + look} r={1.6} fill="#FFFFFF" />
    </G>
  );
}

function Mouth({ y, mood, open }: { y: number; mood: MascotMood; open: boolean }) {
  if (mood === 'talking' && open) {
    return <Ellipse cx={50} cy={y + 1} rx={5} ry={4} fill={INK} />;
  }
  if (mood === 'thinking') {
    return <Path d={`M45 ${y + 1} L55 ${y}`} stroke={INK} strokeWidth={3} strokeLinecap="round" />;
  }
  if (mood === 'listening') {
    return <Ellipse cx={50} cy={y + 1} rx={3} ry={2.5} fill={INK} />;
  }
  return <Path d={`M43 ${y} Q50 ${y + 7} 57 ${y}`} stroke={INK} strokeWidth={3} strokeLinecap="round" fill="none" />;
}

function Cheeks({ y, spread = 22 }: { y: number; spread?: number }) {
  return (
    <G opacity={0.35}>
      <Ellipse cx={50 - spread} cy={y} rx={5} ry={3} fill="#F472B6" />
      <Ellipse cx={50 + spread} cy={y} rx={5} ry={3} fill="#F472B6" />
    </G>
  );
}

function Body({ kind, color, closed, mood, mouthOpen }: {
  kind: MascotKind; color: string; closed: boolean; mood: MascotMood; mouthOpen: boolean;
}) {
  const dark = shade(color, -40);
  const light = shade(color, 45);
  switch (kind) {
    case 'LLAMA':
      return (
        <G>
          <Ellipse cx={34} cy={20} rx={6} ry={13} fill={color} stroke={dark} strokeWidth={2} />
          <Ellipse cx={66} cy={20} rx={6} ry={13} fill={color} stroke={dark} strokeWidth={2} />
          <Rect x={22} y={26} width={56} height={62} rx={26} fill={color} stroke={dark} strokeWidth={2} />
          <Path d="M30 34 Q38 24 46 32 Q54 22 62 32 Q70 26 72 36 Q60 40 50 38 Q40 40 30 34Z" fill={light} />
          <Eyes y={52} closed={closed} mood={mood} />
          <Ellipse cx={50} cy={70} rx={14} ry={10} fill={light} />
          <Mouth y={70} mood={mood} open={mouthOpen} />
          <Cheeks y={62} />
        </G>
      );
    case 'CAPYBARA':
      return (
        <G>
          <Circle cx={28} cy={28} r={7} fill={dark} />
          <Circle cx={72} cy={28} r={7} fill={dark} />
          <Rect x={14} y={24} width={72} height={64} rx={30} fill={color} />
          <Rect x={30} y={56} width={40} height={26} rx={13} fill={dark} opacity={0.55} />
          <Eyes y={46} spread={16} closed={closed} mood={mood} />
          <Ellipse cx={44} cy={62} rx={2.2} ry={3} fill={INK} />
          <Ellipse cx={56} cy={62} rx={2.2} ry={3} fill={INK} />
          <Mouth y={72} mood={mood} open={mouthOpen} />
        </G>
      );
    case 'CAT':
      return (
        <G>
          <Path d="M20 40 L26 10 L44 30 Z" fill={color} stroke={dark} strokeWidth={2} strokeLinejoin="round" />
          <Path d="M80 40 L74 10 L56 30 Z" fill={color} stroke={dark} strokeWidth={2} strokeLinejoin="round" />
          <Path d="M26 34 L28 20 L37 30 Z" fill="#F9A8D4" />
          <Path d="M74 34 L72 20 L63 30 Z" fill="#F9A8D4" />
          <Circle cx={50} cy={56} r={34} fill={color} stroke={dark} strokeWidth={2} />
          <Eyes y={52} spread={14} closed={closed} mood={mood} />
          <Path d="M47 61 L53 61 L50 64 Z" fill="#F472B6" />
          <Mouth y={67} mood={mood} open={mouthOpen} />
          <G stroke={dark} strokeWidth={1.5} strokeLinecap="round">
            <Path d="M24 60 L36 62" />
            <Path d="M24 67 L36 66" />
            <Path d="M76 60 L64 62" />
            <Path d="M76 67 L64 66" />
          </G>
        </G>
      );
    case 'DOG':
      return (
        <G>
          <Circle cx={50} cy={54} r={34} fill={color} />
          <Ellipse cx={20} cy={46} rx={11} ry={20} fill={dark} transform="rotate(15 20 46)" />
          <Ellipse cx={80} cy={46} rx={11} ry={20} fill={dark} transform="rotate(-15 80 46)" />
          <Ellipse cx={50} cy={68} rx={18} ry={13} fill={light} />
          <Eyes y={48} spread={14} closed={closed} mood={mood} />
          <Ellipse cx={50} cy={61} rx={6} ry={4.5} fill={INK} />
          <Mouth y={70} mood={mood} open={mouthOpen} />
        </G>
      );
    case 'CONFI':
    default:
      return (
        <G>
          {/* A sprout: Confío's money that grows. */}
          <Path d="M50 22 Q50 12 50 8" stroke={dark} strokeWidth={3} strokeLinecap="round" />
          <Path d="M50 12 Q40 2 32 8 Q40 16 50 12Z" fill="#34D399" stroke={dark} strokeWidth={1.5} />
          <Path d="M50 12 Q60 2 68 8 Q60 16 50 12Z" fill="#6EE7B7" stroke={dark} strokeWidth={1.5} />
          <Path d="M50 20 C78 20 88 38 88 58 C88 80 72 92 50 92 C28 92 12 80 12 58 C12 38 22 20 50 20Z" fill={color} />
          <Ellipse cx={36} cy={36} rx={10} ry={6} fill="#FFFFFF" opacity={0.25} transform="rotate(-25 36 36)" />
          <Eyes y={54} closed={closed} mood={mood} />
          <Mouth y={66} mood={mood} open={mouthOpen} />
          <Cheeks y={62} />
        </G>
      );
  }
}

type Props = {
  kind?: MascotKind | string;
  // A pet the user created (signed image URL). Moods are shown through
  // motion, since a drawing can't blink: bob, talk pulse, thinking tilt, hop.
  imageUrl?: string | null;
  color?: string;
  size?: number;
  mood?: MascotMood;
  animated?: boolean;
};

export default function AssistantMascot(props: Props) {
  if (props.kind === 'CUSTOM' && props.imageUrl) {
    return (
      <CustomPetMascot imageUrl={props.imageUrl} size={props.size ?? 56} mood={props.mood ?? 'idle'}
        animated={props.animated ?? true} />
    );
  }
  return <BuiltInMascot {...props} />;
}

function BuiltInMascot({ kind = 'CONFI', color, size = 56, mood = 'idle', animated = true }: Props) {
  const safeKind = (MASCOTS.some((m) => m.kind === kind) ? kind : 'CONFI') as MascotKind;
  const fill = color && /^#[0-9A-Fa-f]{6}$/.test(color) ? color : defaultMascotColor(safeKind);
  const [blink, setBlink] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(false);
  const bob = useSharedValue(0);

  useEffect(() => {
    if (!animated) {
      return undefined;
    }
    let closeTimer: ReturnType<typeof setTimeout> | undefined;
    const timer = setInterval(() => {
      setBlink(true);
      closeTimer = setTimeout(() => setBlink(false), 140);
    }, 3800);
    return () => {
      clearInterval(timer);
      if (closeTimer) {
        clearTimeout(closeTimer);
      }
    };
  }, [animated]);

  useEffect(() => {
    if (mood !== 'talking') {
      setMouthOpen(false);
      return undefined;
    }
    const timer = setInterval(() => setMouthOpen((open) => !open), 180);
    return () => clearInterval(timer);
  }, [mood]);

  useEffect(() => {
    if (!animated) {
      bob.value = 0;
      return undefined;
    }
    const lift = mood === 'thinking' || mood === 'listening' ? -4 : -2.5;
    const period = mood === 'thinking' ? 420 : 1400;
    bob.value = withRepeat(
      withSequence(
        withTiming(lift, { duration: period, easing: Easing.inOut(Easing.quad) }),
        withTiming(0, { duration: period, easing: Easing.inOut(Easing.quad) }),
      ),
      -1,
      false,
    );
    return () => cancelAnimation(bob);
  }, [animated, mood, bob]);

  const style = useAnimatedStyle(() => ({ transform: [{ translateY: bob.value * (size / 56) }] }));

  return (
    <View style={{ width: size, height: size }} accessible={false}>
      <Animated.View style={style}>
        <Svg width={size} height={size} viewBox="0 0 100 100">
          <Body kind={safeKind} color={fill} closed={blink} mood={mood} mouthOpen={mouthOpen} />
        </Svg>
      </Animated.View>
    </View>
  );
}

// The signed URL's query changes on every refresh, but each pet image has its
// own path. Keep showing the URL already loaded while the path is the same, so
// a re-signed URL doesn't blank the photo; switch when the pet changes, or when
// the old URL stops loading (expired).
const imagePath = (url: string) => url.split('?')[0];

function CustomPetMascot({ imageUrl, size, mood, animated }: { imageUrl: string; size: number; mood: MascotMood; animated: boolean }) {
  const [shownUrl, setShownUrl] = useState(imageUrl);
  // The current URL itself failed (expired, or the image is gone): show Confi
  // rather than an empty circle until a new URL arrives.
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
    setShownUrl((current) => (imagePath(current) === imagePath(imageUrl) ? current : imageUrl));
  }, [imageUrl]);
  const lift = useSharedValue(0);
  const scale = useSharedValue(1);
  const tilt = useSharedValue(0);

  useEffect(() => {
    cancelAnimation(lift);
    cancelAnimation(scale);
    cancelAnimation(tilt);
    lift.value = 0;
    scale.value = 1;
    tilt.value = 0;
    if (!animated) {
      return undefined;
    }
    const ease = Easing.inOut(Easing.quad);
    const loop = (v: typeof lift, to: number, ms: number) =>
      (v.value = withRepeat(withSequence(withTiming(to, { duration: ms, easing: ease }), withTiming(0, { duration: ms, easing: ease })), -1, false));
    if (mood === 'talking') {
      scale.value = withRepeat(withSequence(withTiming(1.06, { duration: 160 }), withTiming(0.98, { duration: 160 })), -1, true);
    } else if (mood === 'thinking') {
      tilt.value = withRepeat(withSequence(withTiming(-6, { duration: 420, easing: ease }), withTiming(6, { duration: 420, easing: ease })), -1, true);
    } else if (mood === 'listening') {
      scale.value = withRepeat(withSequence(withTiming(1.04, { duration: 600, easing: ease }), withTiming(1, { duration: 600, easing: ease })), -1, false);
    } else if (mood === 'happy') {
      lift.value = withRepeat(withSequence(withTiming(-5, { duration: 220 }), withTiming(0, { duration: 220 }), withTiming(0, { duration: 900 })), -1, false);
    } else {
      loop(lift, -2.5, 1400);
    }
    return () => {
      cancelAnimation(lift);
      cancelAnimation(scale);
      cancelAnimation(tilt);
    };
  }, [animated, mood, lift, scale, tilt]);

  const style = useAnimatedStyle(() => ({
    transform: [
      { translateY: lift.value * (size / 56) },
      { scale: scale.value },
      { rotate: `${tilt.value}deg` },
    ],
  }));

  if (failed) {
    return <BuiltInMascot size={size} mood={mood} animated={animated} />;
  }
  return (
    <View style={{ width: size, height: size }} accessible={false}>
      <Animated.View style={style}>
        <Image
          source={{ uri: shownUrl }}
          style={{ width: size, height: size, borderRadius: size / 2 }}
          resizeMode="cover"
          onError={() => {
            if (shownUrl === imageUrl) {
              setFailed(true);
            } else {
              setShownUrl(imageUrl);
            }
          }}
        />
      </Animated.View>
    </View>
  );
}

export { isLight as isLightColor };
