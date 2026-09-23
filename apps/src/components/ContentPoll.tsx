import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useFragment, useMutation } from '@apollo/client';
import { VOTE_ON_CONTENT_POLL } from '../apollo/mutations';
import { colors } from '../config/theme';

export type ContentPollData = {
  id: string;
  question: string;
  closed: boolean;
  totalVotes: number;
  viewerOptionId?: string | null;
  options: Array<{ id: string; label: string; count: number }>;
};

const POLL_FRAGMENT = gql`
  fragment ContentPollView on ContentPollType {
    id question closed totalVotes viewerOptionId options { id label count }
  }
`;

export function ContentPoll({ poll }: { poll?: ContentPollData | null }) {
  return poll ? <PollVoting key={poll.id} poll={poll} /> : null;
}

function PollVoting({ poll: initialPoll }: { poll: ContentPollData }) {
  const { data, complete } = useFragment<ContentPollData>({
    fragment: POLL_FRAGMENT,
    from: { __typename: 'ContentPollType', id: initialPoll.id },
  });
  const poll = complete ? data : initialPoll;
  const [vote, { loading }] = useMutation(VOTE_ON_CONTENT_POLL);
  const inFlight = useRef(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState('');

  const submit = async (optionId: string) => {
    if (inFlight.current || poll.closed || optionId === poll.viewerOptionId) return;
    inFlight.current = true;
    setPendingId(optionId);
    setError('');
    try {
      await vote({ variables: { contentItemId: poll.id, optionId } });
      // The normalized ContentPollType cache entry updates every surface.
    } catch {
      setError('No se pudo guardar tu voto. Intenta de nuevo.');
    } finally {
      inFlight.current = false;
      setPendingId(null);
    }
  };

  // Results stay hidden until the viewer answers so the tally can't steer the vote.
  const showResults = poll.closed || !!poll.viewerOptionId;
  const leadingCount = Math.max(0, ...poll.options.map(option => option.count));
  const votes = `${poll.totalVotes} ${poll.totalVotes === 1 ? 'voto' : 'votos'}`;
  const status = poll.closed ? 'Encuesta cerrada'
    : poll.viewerOptionId ? 'Toca otra opción para cambiar tu voto'
    : 'Vota para ver los resultados';

  return (
    <View style={styles.container}>
      <View style={styles.eyebrowRow}>
        <Icon name="bar-chart-2" size={13} color={colors.successText} />
        <Text style={styles.eyebrow}>Encuesta</Text>
      </View>
      <Text style={styles.question}>{poll.question}</Text>
      <View style={styles.options}>
        {poll.options.map(option => (
          <PollOption key={option.id} label={option.label} count={option.count}
            percent={poll.totalVotes ? Math.round(option.count * 100 / poll.totalVotes) : 0}
            selected={poll.viewerOptionId === option.id}
            leading={option.count > 0 && option.count === leadingCount}
            pending={pendingId === option.id}
            showResults={showResults} disabled={loading || poll.closed}
            onPress={() => { void submit(option.id); }} />
        ))}
      </View>
      <Text style={styles.caption}>{showResults ? `${votes} · ${status}` : status}</Text>
      {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    </View>
  );
}

type PollOptionProps = {
  label: string; count: number; percent: number;
  selected: boolean; leading: boolean; pending: boolean;
  showResults: boolean; disabled: boolean; onPress: () => void;
};

function PollOption({ label, count, percent, selected, leading, pending, showResults, disabled, onPress }: PollOptionProps) {
  const target = showResults ? percent : 0;
  const fill = useRef(new Animated.Value(target)).current;
  useEffect(() => {
    const animation = Animated.timing(fill, { toValue: target, duration: 420, useNativeDriver: false });
    animation.start();
    return () => animation.stop();
  }, [fill, target]);

  return (
    <Pressable accessibilityRole="radio"
      accessibilityLabel={showResults ? `${label}, ${count} ${count === 1 ? 'voto' : 'votos'}, ${percent}%` : label}
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled} onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        selected && styles.optionSelected,
        pressed && !showResults && styles.optionPressed,
      ]}>
      {showResults && (
        <Animated.View style={[styles.fill, selected && styles.fillSelected,
          { width: fill.interpolate({ inputRange: [0, 100], outputRange: ['0%', '100%'] }) }]} />
      )}
      {pending ? (
        <ActivityIndicator size="small" color={colors.primaryDark} style={styles.indicator} />
      ) : selected ? (
        <Icon name="check-circle" size={18} color={colors.successText} style={styles.indicator} />
      ) : !showResults ? (
        <View style={[styles.indicator, styles.radio]} />
      ) : null}
      <Text style={[styles.label, (selected || (showResults && leading)) && styles.labelStrong]} numberOfLines={3}>
        {label}
      </Text>
      {showResults && (
        <Text style={[styles.percent, (selected || leading) && styles.percentStrong]}>{percent}%</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: {
    marginVertical: 12, padding: 14, borderRadius: 16,
    backgroundColor: colors.neutral, borderWidth: 1, borderColor: colors.borderLight,
  },
  eyebrowRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: 6 },
  eyebrow: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase', color: colors.successText },
  question: { fontSize: 16, lineHeight: 22, fontWeight: '700', color: colors.dark, marginBottom: 12 },
  options: { gap: 8 },
  option: {
    minHeight: 48, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, backgroundColor: '#FFFFFF',
    overflow: 'hidden', flexDirection: 'row', alignItems: 'center', gap: 10,
  },
  optionSelected: { borderColor: colors.primaryDark },
  optionPressed: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  fill: { position: 'absolute', top: 0, bottom: 0, left: 0, backgroundColor: colors.neutralDark },
  fillSelected: { backgroundColor: colors.primaryLight },
  indicator: { width: 18, height: 18 },
  radio: { borderRadius: 9, borderWidth: 2, borderColor: colors.borderMedium },
  label: { flex: 1, fontSize: 15, lineHeight: 20, color: colors.text.primary },
  labelStrong: { fontWeight: '600', color: colors.dark },
  percent: { fontSize: 14, fontWeight: '600', color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  percentStrong: { fontWeight: '700', color: colors.dark },
  caption: { marginTop: 10, fontSize: 12, color: colors.text.secondary },
  error: { marginTop: 6, fontSize: 13, color: colors.error.text },
});
