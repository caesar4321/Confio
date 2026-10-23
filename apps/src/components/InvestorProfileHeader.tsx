import React, { useState } from 'react';
import { ActivityIndicator, Image, InteractionManager, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { Text } from './common/AppText';
import { BylineAvatar } from './PostByline';
import { CommunityRulesSheet } from './CommunityRulesSheet';
import { colors } from '../config/theme';
import { PictureKind, useCommunityPicture } from '../hooks/useCommunityPicture';
import type { InvestorAccess } from './InvestorLockCard';

export type InvestorProfile = {
  userId: string;
  isSelf: boolean;
  bio: string;
  coverUrl?: string | null;
  access: InvestorAccess;
  mutualCount: number;
  mutuals: { userId: string; username: string; avatarUrl?: string | null }[];
  canMessage: boolean;
  canTip: boolean;
  // Your own profile only (never public).
  tipsReceivedUsd?: string | null;
};

type Member = {
  username: string;
  avatarUrl?: string | null;
  followerCount: number;
  followingCount: number;
  isSelf: boolean;
  isFollowing: boolean;
  notify: boolean;
};

type Props = {
  member: Member;
  investor: InvestorProfile | null;
  followBusy: boolean;
  notifyBusy: boolean;
  onToggleFollow: () => void;
  onToggleNotify: () => void;
  onMore: () => void;
  onEditBio: () => void;
  onOpenMutual?: (userId: string) => void;
  onMessage?: () => void;
  onTip?: () => void;
  refreshKey?: number;
};

const COVER_ASPECT = 3;
const AVATAR = 84;

/** "1 seguidor" / "12 seguidores". */
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Perfil inversor header: cover, avatar, name, bio, follow counts with
 * people in common, and the action row. On your own profile, the cover,
 * avatar and bio are edited right here (each reviewed by AI first).
 */
export function InvestorProfileHeader({
  member,
  investor,
  followBusy,
  notifyBusy,
  onToggleFollow,
  onToggleNotify,
  onMore,
  onEditBio,
  onOpenMutual,
  onMessage,
  onTip,
  refreshKey = 0,
}: Props) {
  const self = member.isSelf;
  const avatar = useCommunityPicture('avatar', self, refreshKey);
  const cover = useCommunityPicture('cover', self && investor !== null, refreshKey);
  const [rulesFor, setRulesFor] = useState<PictureKind | null>(null);

  const pick = async (kind: PictureKind) => {
    const target = kind === 'avatar' ? avatar : cover;
    if ((await target.pick()) === 'rules') setRulesFor(kind);
  };

  const coverUrl = self && cover.available ? cover.url : investor?.coverUrl;
  const avatarUrl = self && avatar.available ? avatar.url : member.avatarUrl;
  const message = self ? cover.message || avatar.message : null;
  const reviewing = self && (cover.pending || avatar.pending);

  return (
    <View>
      <View style={styles.cover}>
        {coverUrl ? (
          <Image source={{ uri: coverUrl }} style={styles.coverImage} accessibilityIgnoresInvertColors />
        ) : (
          <Svg width="100%" height="100%" preserveAspectRatio="none" viewBox="0 0 300 100">
            <Defs>
              <LinearGradient id="cover" x1="0" y1="0" x2="1" y2="1">
                <Stop offset="0" stopColor={colors.primaryLight} />
                <Stop offset="1" stopColor={colors.primary} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="300" height="100" fill="url(#cover)" />
          </Svg>
        )}
        {self && cover.available ? (
          <EditBadge
            busy={cover.uploading}
            onPress={() => { void pick('cover'); }}
            label="Cambiar portada"
            style={styles.coverEdit}
          />
        ) : null}
      </View>

      <View style={styles.avatarRow}>
        <View style={styles.avatarRing}>
          {avatarUrl ? (
            <Image source={{ uri: avatarUrl }} style={styles.avatarImage} />
          ) : (
            <BylineAvatar name={member.username} avatarUrl={null} size={AVATAR} />
          )}
          {self && avatar.available ? (
            <EditBadge
              busy={avatar.uploading}
              onPress={() => { void pick('avatar'); }}
              label="Cambiar foto de perfil"
              style={styles.avatarEdit}
            />
          ) : null}
        </View>
        {self ? null : (
          <View style={styles.actions}>
            {investor?.canMessage && onMessage ? (
              <RoundButton icon="send" label="Enviar mensaje" onPress={onMessage} />
            ) : null}
            {investor?.canTip && onTip ? <RoundButton icon="gift" label="Enviar propina" onPress={onTip} /> : null}
            {member.isFollowing ? (
              <RoundButton
                icon={member.notify ? 'bell' : 'bell-off'}
                label={member.notify ? 'Silenciar sus publicaciones' : 'Avisarme de sus publicaciones'}
                onPress={onToggleNotify}
                busy={notifyBusy}
                active={member.notify}
              />
            ) : null}
            <Pressable
              onPress={onToggleFollow}
              disabled={followBusy}
              style={({ pressed }) => [
                styles.followButton,
                member.isFollowing ? styles.followingButton : styles.followPrimary,
                (pressed || followBusy) && styles.pressed,
              ]}
              accessibilityRole="button"
              accessibilityState={{ selected: member.isFollowing, busy: followBusy }}
              accessibilityLabel={member.isFollowing ? 'Siguiendo. Toca para dejar de seguir.' : 'Seguir'}
            >
              {followBusy ? (
                <ActivityIndicator size="small" color={member.isFollowing ? colors.dark : colors.white} />
              ) : (
                <Text style={[styles.followText, member.isFollowing && styles.followingText]}>
                  {member.isFollowing ? 'Siguiendo' : 'Seguir'}
                </Text>
              )}
            </Pressable>
            <RoundButton icon="more-horizontal" label="Más opciones" onPress={onMore} />
          </View>
        )}
      </View>

      <Text style={styles.name} numberOfLines={1}>{member.username}</Text>
      {investor ? (
        self ? (
          <Pressable onPress={onEditBio} hitSlop={6} accessibilityRole="button" accessibilityLabel="Editar descripción">
            <Text style={[styles.bio, !investor.bio && styles.bioPlaceholder]}>
              {investor.bio || 'Agrega una descripción'}
              {'  '}
              <Icon name="edit-2" size={13} color={colors.textSecondary} />
            </Text>
          </Pressable>
        ) : investor.bio ? (
          <Text style={styles.bio}>{investor.bio}</Text>
        ) : null
      ) : null}
      {self && investor?.tipsReceivedUsd && Number(investor.tipsReceivedUsd) > 0 ? (
        <Text style={styles.status}>{`🎁 Propinas recibidas: $${investor.tipsReceivedUsd}`}</Text>
      ) : null}
      {reviewing ? <Text style={styles.status}>Revisando tu imagen… suele tardar unos segundos.</Text> : null}
      {message ? <Text style={styles.refused}>{message}</Text> : null}

      <View style={styles.stats}>
        <Text style={styles.stat}>
          <Text style={styles.statValue}>{member.followingCount}</Text> siguiendo
        </Text>
        <Text style={styles.stat}>
          <Text style={styles.statValue}>{member.followerCount}</Text>
          {member.followerCount === 1 ? ' seguidor' : ' seguidores'}
        </Text>
        {investor && investor.mutualCount > 0 ? (
          <Pressable
            onPress={() => investor.mutuals[0] && onOpenMutual?.(investor.mutuals[0].userId)}
            style={styles.mutuals}
            accessibilityRole="button"
            accessibilityLabel={`${plural(investor.mutualCount, 'seguidor', 'seguidores')} en común`}
          >
            <View style={styles.mutualAvatars}>
              {investor.mutuals.slice(0, 3).map((m, i) => (
                <View key={m.userId} style={[styles.mutualAvatar, i > 0 && styles.mutualOverlap]}>
                  <BylineAvatar name={m.username} avatarUrl={m.avatarUrl} size={20} />
                </View>
              ))}
            </View>
            <Text style={styles.stat}>{`${investor.mutualCount} en común`}</Text>
          </Pressable>
        ) : null}
      </View>

      <CommunityRulesSheet
        visible={rulesFor !== null}
        onAccepted={() => {
          const kind = rulesFor;
          setRulesFor(null);
          if (!kind) return;
          const target = kind === 'avatar' ? avatar : cover;
          target.refetch().catch(() => {});
          // Let the sheet finish closing: iOS can't present the picker over a dismissing modal.
          InteractionManager.runAfterInteractions(() => {
            setTimeout(() => { void target.pick(true); }, 450);
          });
        }}
        onClose={() => setRulesFor(null)}
      />
    </View>
  );
}

function EditBadge({ busy, onPress, label, style }: { busy: boolean; onPress: () => void; label: string; style: object }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      hitSlop={8}
      style={({ pressed }) => [styles.editBadge, style, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={label}
    >
      {busy ? <ActivityIndicator size="small" color={colors.white} /> : <Icon name="edit-2" size={14} color={colors.white} />}
    </Pressable>
  );
}

function RoundButton({
  icon,
  label,
  onPress,
  busy,
  active,
}: {
  icon: string;
  label: string;
  onPress: () => void;
  busy?: boolean;
  active?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      hitSlop={6}
      style={({ pressed }) => [styles.round, (pressed || busy) && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ busy: Boolean(busy) }}
    >
      <Icon name={icon} size={18} color={active ? colors.primaryDeep : colors.dark} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  cover: {
    width: '100%',
    aspectRatio: COVER_ASPECT,
    borderRadius: 16,
    overflow: 'hidden',
    backgroundColor: colors.primaryLight,
  },
  coverImage: { width: '100%', height: '100%' },
  coverEdit: { position: 'absolute', right: 10, bottom: 10 },
  avatarRow: {
    marginTop: -AVATAR / 2,
    paddingHorizontal: 12,
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
  },
  avatarRing: {
    width: AVATAR + 6,
    height: AVATAR + 6,
    borderRadius: (AVATAR + 6) / 2,
    padding: 3,
    backgroundColor: colors.neutral,
  },
  avatarImage: { width: AVATAR, height: AVATAR, borderRadius: AVATAR / 2 },
  avatarEdit: { position: 'absolute', right: 0, bottom: 0 },
  editBadge: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dark,
    borderWidth: 2,
    borderColor: colors.white,
  },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingBottom: 2 },
  round: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderMedium,
  },
  followButton: {
    minWidth: 104,
    height: 40,
    paddingHorizontal: 18,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  followPrimary: { backgroundColor: colors.dark },
  followingButton: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.borderMedium },
  followText: { fontSize: 15, fontWeight: '600', color: colors.white },
  followingText: { color: colors.dark },
  pressed: { opacity: 0.7 },
  name: { marginTop: 10, paddingHorizontal: 4, fontSize: 22, fontWeight: '700', color: colors.dark },
  bio: { marginTop: 4, paddingHorizontal: 4, fontSize: 15, lineHeight: 21, color: colors.text.primary },
  bioPlaceholder: { color: colors.textSecondary },
  status: { marginTop: 6, paddingHorizontal: 4, fontSize: 13, color: colors.textSecondary },
  refused: { marginTop: 6, paddingHorizontal: 4, fontSize: 13, color: colors.error.text },
  stats: { marginTop: 10, paddingHorizontal: 4, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 14 },
  stat: { fontSize: 14, color: colors.textSecondary },
  statValue: { fontWeight: '700', color: colors.dark },
  mutuals: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  mutualAvatars: { flexDirection: 'row' },
  mutualAvatar: { borderRadius: 11, borderWidth: 1, borderColor: colors.white },
  mutualOverlap: { marginLeft: -6 },
});
