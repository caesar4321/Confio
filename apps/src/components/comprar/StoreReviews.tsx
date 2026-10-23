import React, { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { GET_STORE_REVIEWS } from '../../services/comprar';
import { formatRating } from '../../utils/comprarFormat';
import { formatDecimal } from '../../utils/numberLocale';
import { useNumberLocale } from '../../contexts/NumberLocaleProvider';

const PAGE = 10;

type Props = {
  storeId: string;
  avgRating?: number | string | null;
  ratingCount?: number | null;
  /** Show only this many, with a "see all" link (product page). */
  preview?: number;
  onSeeAll?: () => void;
};

export const Stars = ({ value, size = 14 }: { value: number; size?: number }) => (
  <View style={styles.stars} accessibilityLabel={`${value} de 5 estrellas`}>
    {[1, 2, 3, 4, 5].map((n) => (
      <Icon key={n} name="star" size={size} color={n <= Math.round(value) ? '#F59E0B' : '#E5E7EB'} />
    ))}
  </View>
);

/**
 * "Opiniones": what buyers of completed orders said. Every rating counts;
 * a review's text shows once moderation approved it.
 */
export const StoreReviews = ({ storeId, avgRating, ratingCount, preview, onSeeAll }: Props) => {
  useNumberLocale(); // amounts follow the user's number format, live
  const { data, loading, error, refetch, fetchMore } = useQuery(GET_STORE_REVIEWS, {
    variables: { storeId, limit: preview ?? PAGE, offset: 0 },
    fetchPolicy: 'cache-and-network',
  });
  const reviews: any[] = data?.marketplaceStoreReviews || [];
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const count = ratingCount ?? 0;

  const more = async () => {
    setLoadingMore(true);
    try {
      const { data: next } = await fetchMore({
        variables: { storeId, limit: PAGE, offset: reviews.length },
        // A review posted between pages shifts the offset: never show one twice.
        updateQuery: (prev: any, { fetchMoreResult }: any) => {
          const seen = new Set((prev?.marketplaceStoreReviews || []).map((r: any) => r.id));
          return {
            marketplaceStoreReviews: [...(prev?.marketplaceStoreReviews || []),
              ...(fetchMoreResult?.marketplaceStoreReviews || []).filter((r: any) => !seen.has(r.id))],
          };
        },
      });
      if ((next?.marketplaceStoreReviews || []).length < PAGE) setHasMore(false);
    } catch {
      // keep the list
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title}>Opiniones</Text>
        {count ? (
          <View style={styles.summary}>
            <Icon name="star" size={15} color="#F59E0B" />
            <Text style={styles.summaryValue}>{formatRating(avgRating ?? 0)}</Text>
            <Text style={styles.summaryCount}>({formatDecimal(count, { decimals: 0 })})</Text>
          </View>
        ) : null}
      </View>
      {loading && !reviews.length ? <ActivityIndicator color={colors.primaryDark} /> : null}
      {/* "Couldn't load" must never read as "nobody reviewed this store". */}
      {!loading && !reviews.length && error ? (
        <Pressable onPress={() => { void refetch().catch(() => {}); }} accessibilityRole="button" testID="reviews-retry">
          <Text style={styles.empty}>No pudimos cargar las opiniones. Toca para reintentar.</Text>
        </Pressable>
      ) : null}
      {!loading && !reviews.length && !error ? (
        <Text style={styles.empty}>Aún no hay opiniones. Las dejan quienes reciben su pedido.</Text>
      ) : null}
      {reviews.map((r) => (
        <View key={r.id} style={styles.review} testID={`review-${r.id}`}>
          <View style={styles.reviewHead}>
            <Stars value={r.rating} />
            <Text style={styles.meta} numberOfLines={1}>
              @{r.author} · {new Date(r.createdAt).toLocaleDateString('es-BO', { day: 'numeric', month: 'short' })}
            </Text>
          </View>
          {r.comment ? <Text style={styles.comment}>{r.comment}</Text> : null}
          <Text style={styles.product} numberOfLines={1}>Compró: {r.productTitle}</Text>
        </View>
      ))}
      {preview && onSeeAll && count > reviews.length ? (
        <Pressable onPress={onSeeAll} style={styles.link} accessibilityRole="button">
          <Text style={styles.linkText}>Ver todas las opiniones</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDeep} />
        </Pressable>
      ) : null}
      {!preview && hasMore && reviews.length >= PAGE ? (
        <Pressable onPress={() => { void more(); }} style={styles.link} disabled={loadingMore} accessibilityRole="button">
          {loadingMore ? <ActivityIndicator color={colors.primaryDark} /> : <Text style={styles.linkText}>Ver más opiniones</Text>}
        </Pressable>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  summary: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  summaryValue: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  summaryCount: { fontSize: 13, color: colors.text.secondary },
  empty: { fontSize: 13, color: colors.text.secondary },
  review: { backgroundColor: colors.white, borderRadius: 14, padding: 12, gap: 6, borderWidth: 1, borderColor: colors.borderLight },
  reviewHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  stars: { flexDirection: 'row', gap: 2 },
  meta: { flex: 1, fontSize: 12, color: colors.text.secondary },
  comment: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
  product: { fontSize: 12, color: colors.text.light },
  link: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingVertical: 8 },
  linkText: { fontSize: 14, fontWeight: '600', color: colors.primaryDeep },
});
