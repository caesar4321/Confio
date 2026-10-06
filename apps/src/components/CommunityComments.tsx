import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Image, Platform, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from './common/AppText';
import { colors } from '../config/theme';
import { ReportReasonSheet } from './ReportReasonSheet';
import { ReactionBar } from './ReactionBar';
import { CommunityRulesSheet } from './CommunityRulesSheet';
import {
  BLOCK_COMMUNITY_MEMBER,
  CREATE_COMMUNITY_COMMENT,
  DELETE_COMMUNITY_COMMENT,
  REACT_TO_COMMUNITY_COMMENT,
  REPORT_COMMUNITY_COMMENT,
} from '../apollo/mutations';
import { GET_COMMUNITY_COMMENTS, GET_COMMUNITY_POST_PARTICIPANTS } from '../apollo/queries';
import { usePollWhile } from '../hooks/usePollWhile';
import { notifyMemberBlocked } from '../services/communityEvents';

type Participant = { id: string; name: string; isPostAuthor?: boolean; avatarUrl?: string | null };

export type CommunityComment = {
  id: string;
  parentId?: string | null;
  body: string;
  authorId: string;
  authorName: string;
  isPostAuthor: boolean;
  isOwn: boolean;
  canDelete: boolean;
  canReport: boolean;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'FAILED' | 'REMOVED';
  reason?: string | null;
  time: string;
  mentions: Participant[];
  replies?: CommunityComment[];
  replyCount?: number;
  authorAvatarUrl?: string | null;
  reactionSummary?: Array<{ emoji: string; count: number }>;
  viewerReaction?: string | null;
};

function Avatar({ name, url, small = false }: { name: string; url?: string | null; small?: boolean }) {
  const [failed, setFailed] = useState(false);
  const style = small ? styles.avatarSmall : styles.avatar;
  return (
    <View style={style}>
      {url && !failed ? (
        <Image source={{ uri: url }} style={style} onError={() => setFailed(true)} />
      ) : (
        <Text style={styles.avatarText}>{name.charAt(0).toUpperCase()}</Text>
      )}
    </View>
  );
}

type ReplyTarget = { parentId: string; authorName: string };

const PAGE_SIZE = 20;
const POLL_MS = 3000;
// The AI usually answers in seconds; stop polling well after that.
const POLL_GIVE_UP_MS = 90000;
// Matches the server's COMMENT_THREADS_MAX.
const MAX_THREADS = 100;

const fold = (value: string) => value.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The "@partial" being typed at the end of the text, if any. */
export function trailingMentionQuery(text: string): string | null {
  const match = text.match(/(^|\s)@([^\s@]*(?: [^\s@]*\.?)?)$/);
  return match ? match[2] : null;
}

/** Splits a body into plain and "@Name" parts for the names actually tagged. */
export function mentionParts(body: string, names: string[]): Array<{ text: string; mention: boolean }> {
  const unique = Array.from(new Set(names.filter(Boolean))).sort((a, b) => b.length - a.length);
  if (!unique.length) return [{ text: body, mention: false }];
  // A capturing split alternates text, match, text, match…
  const pattern = new RegExp(`(@(?:${unique.map(escapeRegExp).join('|')}))`);
  return body
    .split(pattern)
    .map((part, index) => ({ text: part, mention: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

type PickedMention = { id: string; name: string };

/**
 * Mentions the server should notify: picked people whose "@Name" is still in
 * the text. Tracked by id, so two people who both show as "Ana P." are each
 * kept.
 */
export function mentionIdsInText(text: string, picked: PickedMention[]): string[] {
  // Each "@Name" left in the text accounts for at most one person: when two
  // picked people share a name and one mention is deleted, only the most
  // recently picked stays tagged.
  const byName = new Map<string, string[]>();
  for (const p of picked) byName.set(p.name, [...(byName.get(p.name) || []), p.id]);
  const ids: string[] = [];
  byName.forEach((nameIds, name) => {
    const occurrences = text.split(`@${name}`).length - 1;
    if (occurrences > 0) ids.push(...nameIds.slice(-occurrences));
  });
  return Array.from(new Set(ids));
}

const withMention = (prev: PickedMention[], mention: PickedMention) =>
  prev.some((p) => p.id === mention.id) ? prev : [...prev, mention];

type Props = {
  contentItemId: number;
  canComment: boolean;
  blockMessage?: string | null;
  /** e.g. 'rules_required': offer the rules right here. */
  blockCode?: string | null;
  onRulesAccepted?: () => void;
  maxChars: number;
};

export function CommunityComments({
  contentItemId, canComment, blockMessage, blockCode, onRulesAccepted, maxChars,
}: Props) {
  const client = useApolloClient();
  const variables = { contentItemId: String(contentItemId) };
  // One query for everything loaded: "Ver más" grows the limit, so every
  // refetch and poll re-reads all loaded threads and nothing goes stale.
  const [limit, setLimit] = useState(PAGE_SIZE);
  // Threads opened with "Ver todas las respuestas"; part of the query so
  // polls keep them complete too. The server honours up to 5.
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const { data: freshData, previousData, loading, refetch, startPolling, stopPolling } = useQuery(
    GET_COMMUNITY_COMMENTS,
    {
      variables: { ...variables, offset: 0, limit, expandedThreadIds: expandedIds },
      fetchPolicy: 'network-only',
      notifyOnNetworkStatusChange: false,
    },
  );
  // Keep showing what was there while a bigger page loads.
  const data = freshData ?? previousData;
  const [createComment] = useMutation(CREATE_COMMUNITY_COMMENT);
  const [deleteComment] = useMutation(DELETE_COMMUNITY_COMMENT);
  const [reportComment] = useMutation(REPORT_COMMUNITY_COMMENT);
  const [reactToComment] = useMutation(REACT_TO_COMMUNITY_COMMENT);
  const [blockMember] = useMutation(BLOCK_COMMUNITY_MEMBER);
  const [rulesOpen, setRulesOpen] = useState(false);
  // Reactions answered by the server, shown until the next refetch has them.
  const [reactionOverrides, setReactionOverrides] = useState<
    Record<string, { reactionSummary: Array<{ emoji: string; count: number }>; viewerReaction?: string | null }>
  >({});
  useEffect(() => setReactionOverrides({}), [data]);

  const [text, setText] = useState('');
  const [picked, setPicked] = useState<PickedMention[]>([]);
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportingId, setReportingId] = useState<string | null>(null);
  const [participants, setParticipants] = useState<Participant[] | null>(null);
  const inputRef = useRef<any>(null);

  const page = data?.communityComments;
  const comments: CommunityComment[] = page?.items || [];
  const hasMore = Boolean(page?.hasMore) && limit < MAX_THREADS;
  const loadingMore = loading && Boolean(previousData) && !freshData;
  const totalCount: number = page?.totalCount ?? 0;

  // Keep checking while one of your own comments is still being reviewed.
  const anyPending = comments.some(
    (c) => (c.isOwn && c.status === 'PENDING') || (c.replies || []).some((r) => r.isOwn && r.status === 'PENDING'),
  );
  const pendingKey = comments
    .flatMap((c) => [c, ...(c.replies || [])])
    .filter((c) => c.isOwn && c.status === 'PENDING')
    .map((c) => c.id)
    .join(',');
  usePollWhile(anyPending, startPolling, stopPolling, POLL_MS, POLL_GIVE_UP_MS, pendingKey);
  // Coming back to the post re-reads it, so a review that finished after
  // polling gave up still shows its outcome.
  const focusedOnce = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        return;
      }
      refetch().catch(() => {});
    }, [refetch]),
  );

  const loadParticipants = async () => {
    if (participants !== null) return;
    try {
      const { data: result } = await client.query({
        query: GET_COMMUNITY_POST_PARTICIPANTS,
        variables,
        fetchPolicy: 'network-only',
      });
      setParticipants(result?.communityPostParticipants || []);
    } catch {
      setParticipants([]);
    }
  };

  const mentionQuery = trailingMentionQuery(text);
  const suggestions = useMemo(() => {
    if (mentionQuery === null || !participants) return [];
    const query = fold(mentionQuery);
    return participants.filter((p) => fold(p.name).startsWith(query)).slice(0, 5);
  }, [mentionQuery, participants]);

  const onChangeText = (next: string) => {
    setText(next);
    if (trailingMentionQuery(next) !== null) void loadParticipants();
  };

  const pickMention = (participant: Participant) => {
    const replaced = text.replace(/@([^\s@]*(?: [^\s@]*\.?)?)$/, `@${participant.name} `);
    setText(replaced);
    setPicked((prev) => withMention(prev, { id: participant.id, name: participant.name }));
    inputRef.current?.focus?.();
  };

  const startReply = (comment: CommunityComment) => {
    setReplyTo({ parentId: comment.parentId || comment.id, authorName: comment.authorName });
    if (!comment.isOwn) {
      // Replying to someone tags them, like everywhere else.
      setText((prev) => (prev.includes(`@${comment.authorName}`) ? prev : `@${comment.authorName} ${prev}`));
      setPicked((prev) => withMention(prev, { id: comment.authorId, name: comment.authorName }));
    }
    inputRef.current?.focus?.();
  };

  const resetComposer = () => {
    setText('');
    setPicked([]);
    setReplyTo(null);
  };

  const submit = async () => {
    const body = text.trim();
    if (!body || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { data: result } = await createComment({
        variables: {
          ...variables,
          body,
          parentId: replyTo?.parentId || null,
          mentionUserIds: mentionIdsInText(body, picked),
        },
      });
      const outcome = result?.createCommunityComment;
      if (!outcome?.success) {
        if (outcome?.errorCode === 'rules_required') {
          setRulesOpen(true);
          return;
        }
        setError(outcome?.error || 'No pudimos enviar tu comentario.');
        return;
      }
      resetComposer();
      setParticipants(null);
      await refetch();
    } catch {
      setError('No pudimos enviar tu comentario. Revisa tu conexión.');
    } finally {
      setSubmitting(false);
    }
  };

  const loadMore = () => {
    if (loading || !hasMore) return;
    setLimit((current) => Math.min(current + PAGE_SIZE, MAX_THREADS));
  };

  const remove = (comment: CommunityComment) => {
    Alert.alert('¿Eliminar comentario?', comment.parentId ? undefined : 'También se ocultarán sus respuestas.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Eliminar',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteComment({ variables: { commentId: comment.id } });
            await refetch();
          } catch {
            Alert.alert('No pudimos eliminarlo', 'Revisa tu conexión e inténtalo de nuevo.');
          }
        },
      },
    ]);
  };

  const report = async (reason: string) => {
    const commentId = reportingId;
    setReportingId(null);
    if (!commentId) return;
    try {
      const { data: result } = await reportComment({ variables: { commentId, reason } });
      const outcome = result?.reportCommunityComment;
      if (!outcome?.success) {
        Alert.alert('No pudimos enviar tu reporte', outcome?.error || 'Inténtalo de nuevo.');
        return;
      }
      Alert.alert('Gracias por avisarnos', 'Revisaremos este comentario.');
      await refetch();
    } catch {
      Alert.alert('No pudimos enviar tu reporte', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const react = async (comment: CommunityComment, emoji: string) => {
    try {
      const { data: result } = await reactToComment({ variables: { commentId: comment.id, emoji } });
      const outcome = result?.reactToCommunityComment;
      if (outcome?.success) {
        setReactionOverrides((prev) => ({
          ...prev,
          [comment.id]: { reactionSummary: outcome.reactionSummary || [], viewerReaction: outcome.viewerReaction },
        }));
      }
    } catch {
      // The bar keeps its last state; tapping again retries.
    }
  };

  const confirmBlock = (comment: CommunityComment) => {
    Alert.alert(
      `¿Bloquear a ${comment.authorName}?`,
      'No verás sus publicaciones ni comentarios, y no podrá ver los tuyos ni mencionarte. Puedes desbloquear cuando quieras desde Mis publicaciones.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Bloquear',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data: result } = await blockMember({ variables: { userId: comment.authorId } });
              if (!result?.blockCommunityMember?.success) {
                Alert.alert('No pudimos bloquear', result?.blockCommunityMember?.error || 'Inténtalo de nuevo.');
                return;
              }
              notifyMemberBlocked();
              await refetch();
            } catch {
              Alert.alert('No pudimos bloquear', 'Revisa tu conexión e inténtalo de nuevo.');
            }
          },
        },
      ],
    );
  };

  const openMenu = (comment: CommunityComment) => {
    const actions: any[] = [];
    if (comment.canReport) actions.push({ text: 'Reportar', onPress: () => setReportingId(comment.id) });
    if (comment.canDelete) actions.push({ text: 'Eliminar', style: 'destructive', onPress: () => remove(comment) });
    if (!comment.isOwn) actions.push({ text: 'Bloquear', style: 'destructive', onPress: () => confirmBlock(comment) });
    if (!actions.length) return;
    // Android dialogs hold at most three buttons: with three actions, a tap
    // outside cancels instead of a Cancel button.
    const withCancel = Platform.OS !== 'android' || actions.length < 3;
    Alert.alert(
      'Comentario',
      undefined,
      withCancel ? [...actions, { text: 'Cancelar', style: 'cancel' }] : actions,
      { cancelable: true },
    );
  };

  const renderComment = (comment: CommunityComment, isReply = false) => {
    const pending = comment.status === 'PENDING';
    const refused = comment.status === 'REJECTED' || comment.status === 'FAILED';
    const parts = mentionParts(comment.body, comment.mentions.map((m) => m.name));
    return (
      <View key={comment.id} style={[styles.comment, isReply && styles.reply, (pending || refused) && styles.dimmed]}>
        <Avatar name={comment.authorName} url={comment.authorAvatarUrl} small={isReply} />
        <View style={styles.commentMain}>
          <View style={styles.commentHeader}>
            <Text style={styles.authorName}>{comment.authorName}</Text>
            {comment.isPostAuthor ? <Text style={styles.authorBadge}>Autor</Text> : null}
            <Text style={styles.time}>{comment.time}</Text>
            {(comment.canReport || comment.canDelete || !comment.isOwn) && !refused ? (
              <Pressable
                onPress={() => openMenu(comment)}
                hitSlop={10}
                style={styles.menuButton}
                accessibilityRole="button"
                accessibilityLabel="Opciones del comentario"
              >
                <Icon name="more-horizontal" size={16} color={colors.textTertiary} />
              </Pressable>
            ) : null}
          </View>
          <Text style={styles.commentBody}>
            {parts.map((part, index) => (
              <Text key={index} style={part.mention ? styles.mention : undefined}>{part.text}</Text>
            ))}
          </Text>
          {pending ? (
            <View style={styles.pendingRow}>
              <Text style={styles.statusPending}>Revisando…</Text>
              <Pressable onPress={() => { refetch().catch(() => {}); }} hitSlop={8} accessibilityRole="button">
                <Text style={styles.refreshLink}>Actualizar</Text>
              </Pressable>
            </View>
          ) : null}
          {refused ? (
            <View style={styles.refusedRow}>
              <Text style={styles.statusRefused}>{comment.reason || 'No se publicó.'}</Text>
              <Pressable onPress={() => remove(comment)} hitSlop={8} accessibilityRole="button">
                <Text style={styles.linkText}>Eliminar</Text>
              </Pressable>
            </View>
          ) : null}
          {comment.status === 'APPROVED' ? (
            <View style={styles.commentActions}>
              <ReactionBar
                reactions={(reactionOverrides[comment.id] || comment).reactionSummary || []}
                viewerReaction={(reactionOverrides[comment.id] || comment).viewerReaction}
                onReact={(emoji) => { void react(comment, emoji); }}
                limit={2}
              />
              {canComment ? (
                <Pressable onPress={() => startReply(comment)} hitSlop={8} accessibilityRole="button">
                  <Text style={styles.replyLink}>Responder</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </View>
      </View>
    );
  };

  const remaining = maxChars - text.length;
  return (
    <View style={styles.section}>
      <Text style={styles.heading}>
        Comentarios{totalCount ? ` · ${totalCount}` : ''}
      </Text>

      {canComment ? (
        <View style={styles.composer}>
          {replyTo ? (
            <View style={styles.replyingRow}>
              <Text style={styles.replyingText}>Respondiendo a {replyTo.authorName}</Text>
              <Pressable onPress={resetComposer} hitSlop={8} accessibilityRole="button">
                <Text style={styles.linkText}>Cancelar</Text>
              </Pressable>
            </View>
          ) : null}
          <View style={styles.inputRow}>
            <TextInput
              ref={inputRef}
              style={styles.input}
              value={text}
              onChangeText={onChangeText}
              placeholder="Escribe un comentario… usa @ para mencionar"
              placeholderTextColor={colors.textTertiary}
              multiline
              maxLength={maxChars}
              editable={!submitting}
            />
            <Pressable
              onPress={() => { void submit(); }}
              disabled={!text.trim() || submitting}
              style={[styles.send, (!text.trim() || submitting) && styles.sendDisabled]}
              accessibilityRole="button"
              accessibilityLabel="Enviar comentario"
            >
              {submitting ? (
                <ActivityIndicator size="small" color={colors.white} />
              ) : (
                <Icon name="send" size={16} color={colors.white} />
              )}
            </Pressable>
          </View>
          {suggestions.length ? (
            <View style={styles.suggestions}>
              {suggestions.map((participant) => (
                <Pressable
                  key={participant.id}
                  style={({ pressed }) => [styles.suggestion, pressed && styles.suggestionPressed]}
                  onPress={() => pickMention(participant)}
                  accessibilityRole="button"
                >
                  <Avatar name={participant.name} url={participant.avatarUrl} small />
                  <Text style={styles.suggestionName}>{participant.name}</Text>
                  {participant.isPostAuthor ? <Text style={styles.authorBadge}>Autor</Text> : null}
                </Pressable>
              ))}
            </View>
          ) : mentionQuery !== null && participants && participants.length === 0 ? (
            <Text style={styles.hint}>Solo puedes mencionar a quienes participan en esta publicación.</Text>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {remaining < 50 ? <Text style={styles.hint}>{remaining} caracteres restantes</Text> : null}
        </View>
      ) : blockCode === 'rules_required' ? (
        <Pressable onPress={() => setRulesOpen(true)} style={styles.rulesPrompt} accessibilityRole="button">
          <Icon name="book-open" size={14} color={colors.primaryDark} />
          <Text style={styles.linkText}>Acepta las normas de la comunidad para comentar</Text>
        </Pressable>
      ) : blockMessage ? (
        <Text style={styles.blocked}>{blockMessage}</Text>
      ) : null}
      <CommunityRulesSheet
        visible={rulesOpen}
        onAccepted={() => {
          setRulesOpen(false);
          onRulesAccepted?.();
        }}
        onClose={() => setRulesOpen(false)}
      />

      {loading && !page ? (
        <ActivityIndicator style={styles.loading} size="small" color={colors.primary} />
      ) : comments.length === 0 ? (
        <Text style={styles.empty}>Sé la primera persona en comentar.</Text>
      ) : (
        comments.map((comment) => {
          const shownApproved = (comment.replies || []).filter((r) => r.status === 'APPROVED').length;
          const hidden = (comment.replyCount || 0) - shownApproved;
          return (
            <View key={comment.id}>
              {renderComment(comment)}
              {(comment.replies || []).map((reply) => renderComment(reply, true))}
              {hidden > 0 && !expandedIds.includes(comment.id) ? (
                <Pressable
                  onPress={() => setExpandedIds((prev) => [...prev.slice(-4), comment.id])}
                  style={styles.expand}
                  hitSlop={8}
                  accessibilityRole="button"
                >
                  <Text style={styles.linkText}>Ver todas las respuestas ({comment.replyCount})</Text>
                </Pressable>
              ) : null}
            </View>
          );
        })
      )}

      {hasMore ? (
        <Pressable onPress={loadMore} style={styles.more} accessibilityRole="button">
          {loadingMore ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Text style={styles.linkText}>Ver más comentarios</Text>
          )}
        </Pressable>
      ) : null}

      <ReportReasonSheet
        visible={reportingId !== null}
        title="¿Por qué reportas este comentario?"
        onPick={(reason) => { void report(reason); }}
        onClose={() => setReportingId(null)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginTop: 20,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
  },
  heading: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 12,
  },
  composer: {
    marginBottom: 12,
  },
  replyingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  replyingText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
  },
  input: {
    flex: 1,
    minHeight: 42,
    maxHeight: 120,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.textFlat,
    backgroundColor: colors.white,
  },
  send: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: colors.primaryDark,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendDisabled: {
    opacity: 0.4,
  },
  suggestions: {
    marginTop: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    backgroundColor: colors.white,
    overflow: 'hidden',
  },
  suggestion: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  suggestionPressed: {
    backgroundColor: colors.primarySoft,
  },
  suggestionName: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textFlat,
  },
  hint: {
    marginTop: 6,
    fontSize: 12,
    color: colors.textTertiary,
  },
  error: {
    marginTop: 6,
    fontSize: 13,
    color: colors.error.text,
  },
  rulesPrompt: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 12,
    paddingVertical: 4,
  },
  blocked: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 12,
  },
  loading: {
    marginVertical: 12,
  },
  empty: {
    fontSize: 14,
    color: colors.textTertiary,
    paddingVertical: 8,
  },
  comment: {
    flexDirection: 'row',
    gap: 10,
    paddingVertical: 10,
  },
  reply: {
    marginLeft: 42,
    paddingVertical: 8,
  },
  dimmed: {
    opacity: 0.75,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarSmall: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primaryDeep,
  },
  commentMain: {
    flex: 1,
  },
  commentHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  authorName: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textFlat,
  },
  authorBadge: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.primaryDeep,
    backgroundColor: colors.primarySoft,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 6,
    overflow: 'hidden',
  },
  time: {
    fontSize: 12,
    color: colors.textTertiary,
  },
  menuButton: {
    marginLeft: 'auto',
  },
  commentBody: {
    marginTop: 2,
    fontSize: 15,
    lineHeight: 21,
    color: colors.text.primary,
  },
  mention: {
    fontWeight: '600',
    color: colors.primaryDeep,
  },
  pendingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  refreshLink: {
    marginTop: 4,
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  statusPending: {
    marginTop: 4,
    fontSize: 12,
    color: colors.textTertiary,
  },
  refusedRow: {
    marginTop: 4,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  statusRefused: {
    flex: 1,
    fontSize: 12,
    color: colors.error.text,
  },
  commentActions: {
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
  },
  replyLink: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  linkText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  expand: {
    marginLeft: 42,
    paddingVertical: 6,
  },
  more: {
    alignItems: 'center',
    paddingVertical: 12,
  },
});
