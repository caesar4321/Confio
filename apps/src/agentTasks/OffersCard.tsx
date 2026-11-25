// A search across stores, drawn in the chat: the best offers of several stores, each with its price, its
// store, its stars and whether Confío can pay that store. "Comprar aquí" starts the ordinary purchase at that
// store (its own card follows in the chat). The words and pictures are the web's, never Confío's.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { AgentOffer, AgentOffers, BUY_AGENT_OFFER, GET_AGENT_OFFERS } from './api';

const https = (uri: string) => (/^https:\/\//.test(uri) ? uri : '');
// Confío pays it, or the person can still pay it themselves: drawn as good news. Anything else is said plainly.
const PAYS = new Set(['confio']);

function Photo({ uri }: { uri: string }) {
  const [failed, setFailed] = useState(false);
  if (!https(uri) || failed) {
    return <View style={[styles.photo, styles.photoEmpty]}><Icon name="package" size={40} color="#9CA3AF" /></View>;
  }
  return <Image source={{ uri }} style={styles.photo} resizeMode="contain" onError={() => setFailed(true)} />;
}

export function OffersCard({ offersId }: { offersId: string }) {
  const client = useApolloClient();
  const [found, setFound] = useState<AgentOffers | null | undefined>(undefined);
  const [buying, setBuying] = useState<number | null>(null);
  const [started, setStarted] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  useEffect(() => {
    (async () => {
      try {
        const result = await client.query({ query: GET_AGENT_OFFERS, variables: { id: offersId },
          fetchPolicy: 'no-cache' });
        if (alive.current) {
          const data: AgentOffers | null = result.data?.agentOffers ?? null;
          setFound(data);
          setStarted(typeof data?.picked === 'number' ? data.picked : null);
        }
      } catch {
        // A server without it (or none reachable): the note's own words stay.
        if (alive.current) {
          setFound(null);
        }
      }
    })();
  }, [client, offersId]);

  const buy = useCallback(async (index: number) => {
    if (buying !== null) {
      return;
    }
    setBuying(index);
    setNote(null);
    try {
      const result = await client.mutate({ mutation: BUY_AGENT_OFFER, variables: { id: offersId, index },
        fetchPolicy: 'no-cache' });
      const answer = result.data?.buyAgentOffer;
      if (!alive.current) {
        return;
      }
      if (answer?.success) {
        setStarted(index);
      } else {
        setNote(answer?.errors?.[0] || 'No pude empezar la compra. Inténtalo de nuevo.');
      }
    } catch {
      if (alive.current) {
        setNote('No pude empezar la compra. Revisa tu conexión e inténtalo de nuevo.');
      }
    } finally {
      if (alive.current) {
        setBuying(null);
      }
    }
  }, [buying, client, offersId]);

  if (!found || !found.offers.length) {
    return null;
  }
  return (
    <View style={styles.card} accessibilityLabel="Ofertas de varias tiendas">
      <View style={styles.head}>
        <Icon name="shopping-bag" size={16} color={colors.text.secondary} />
        <Text style={styles.headText} numberOfLines={1}>Ofertas en varias tiendas</Text>
      </View>
      <FlatList
        horizontal
        data={found.offers}
        extraData={[buying, started]}
        keyExtractor={(_, index) => String(index)}
        showsHorizontalScrollIndicator={false}
        initialNumToRender={5}
        maxToRenderPerBatch={5}
        windowSize={5}
        contentContainerStyle={styles.offers}
        renderItem={({ item, index }) => (
          <Offer offer={item} busy={buying !== null} buying={buying === index} started={started === index}
            onBuy={() => buy(index)} />
        )}
      />
      {started !== null ? (
        <Text style={styles.cap}>Empecé la compra en {found.offers[started]?.site}. Síguela abajo.</Text>
      ) : (
        <Text style={styles.cap}>Toca «Comprar aquí» y la compro en esa tienda; antes de pagar te muestro el total.</Text>
      )}
      {note ? <Text style={styles.note}>{note}</Text> : null}
    </View>
  );
}

function Offer({ offer, busy, buying, started, onBuy }: {
  offer: AgentOffer; busy: boolean; buying: boolean; started: boolean; onBuy: () => void;
}) {
  const pays = PAYS.has(offer.pay);
  return (
    <View style={[styles.offer, started ? styles.offerStarted : null]}>
      <Photo uri={offer.image} />
      <Text style={styles.title} numberOfLines={3}>{offer.title}</Text>
      {offer.price ? <Text style={styles.price}>{offer.price}</Text> : null}
      <Text style={styles.store} numberOfLines={1}>{offer.store}</Text>
      {offer.rating ? (
        <Text style={styles.rating}
          accessibilityLabel={`${offer.rating} de 5 estrellas${offer.reviews ? `, ${offer.reviews} opiniones` : ''}`}>
          ★ {offer.rating}{offer.reviews ? ` (${offer.reviews})` : ''}
        </Text>
      ) : null}
      <View style={[styles.pay, pays ? styles.payYes : styles.payNo]}>
        <Icon name={pays ? 'check-circle' : 'info'} size={12} color={pays ? colors.primaryDark : '#6B7280'} />
        <Text style={[styles.payText, pays ? styles.payTextYes : null]} numberOfLines={3}>{offer.payText}</Text>
      </View>
      <Pressable disabled={busy || started} onPress={onBuy} accessibilityRole="button"
        accessibilityState={{ disabled: busy || started, busy: buying }}
        accessibilityLabel={`Comprar aquí: ${offer.title}, ${offer.price}, en ${offer.store}. ${offer.payText}`}
        style={[styles.buy, busy && !buying ? styles.buyIdle : null]}>
        <Text style={styles.buyText}>{started ? 'Comprando aquí' : buying ? 'Empezando…' : 'Comprar aquí'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 8, padding: 12, borderRadius: 16, borderWidth: 1, borderColor: '#D1FAE5',
    backgroundColor: colors.background, gap: 10,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headText: { flex: 1, fontSize: 13, color: colors.text.secondary },
  offers: { gap: 10, paddingVertical: 2 },
  offer: {
    width: 168, padding: 10, borderRadius: 14, borderWidth: 1, borderColor: '#E5E7EB',
    backgroundColor: colors.background, gap: 6,
  },
  offerStarted: { borderColor: colors.primaryDark, borderWidth: 2 },
  photo: { width: 132, height: 132, borderRadius: 10, backgroundColor: '#FFFFFF', alignSelf: 'center' },
  photoEmpty: { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.neutralDark },
  title: { fontSize: 14, lineHeight: 19, color: colors.text.primary },
  price: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  store: { fontSize: 13, color: colors.text.secondary },
  rating: { fontSize: 13, color: '#B45309' },
  pay: { flexDirection: 'row', alignItems: 'flex-start', gap: 4, padding: 6, borderRadius: 8 },
  payYes: { backgroundColor: colors.primaryLight },
  payNo: { backgroundColor: '#F3F4F6' },
  payText: { flex: 1, fontSize: 12, lineHeight: 16, color: '#6B7280' },
  payTextYes: { color: colors.primaryDark, fontWeight: '600' },
  buy: {
    minHeight: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryDark, marginTop: 2,
  },
  buyIdle: { opacity: 0.5 },
  buyText: { fontSize: 15, fontWeight: '600', color: '#FFFFFF' },
  cap: { fontSize: 13, color: '#6B7280', textAlign: 'center' },
  note: { fontSize: 14, color: colors.error.text },
});
