import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, ViewStyle } from 'react-native';

interface SkeletonLoaderProps {
  width?: number | string;
  height?: number;
  borderRadius?: number;
  style?: ViewStyle;
}

export const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  width = '100%',
  height = 20,
  borderRadius = 4,
  style,
}) => {
  const shimmerAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(shimmerAnim, {
          toValue: 1,
          duration: 1000,
          useNativeDriver: true,
        }),
        Animated.timing(shimmerAnim, {
          toValue: 0,
          duration: 1000,
          useNativeDriver: true,
        }),
      ])
    ).start();
  }, [shimmerAnim]);

  const opacity = shimmerAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.7],
  });

  return (
    <Animated.View
      style={[
        styles.skeleton,
        {
          width,
          height,
          borderRadius,
          opacity,
        },
        style,
      ]}
    />
  );
};

export const OfferCardSkeleton: React.FC = () => {
  return (
    <View style={styles.cardContainer}>
      <View style={styles.cardHeader}>
        <View style={styles.userInfo}>
          <SkeletonLoader width={40} height={40} borderRadius={20} />
          <View style={styles.userDetails}>
            <SkeletonLoader width={120} height={16} />
            <SkeletonLoader width={80} height={12} style={{ marginTop: 4 }} />
          </View>
        </View>
        <SkeletonLoader width={80} height={24} />
      </View>
      
      <View style={styles.cardContent}>
        <SkeletonLoader width="60%" height={14} />
        <SkeletonLoader width="40%" height={14} style={{ marginTop: 8 }} />
      </View>
      
      <View style={styles.cardFooter}>
        <SkeletonLoader width={100} height={32} borderRadius={6} />
        <SkeletonLoader width={80} height={32} borderRadius={6} />
      </View>
    </View>
  );
};

export const TradeCardSkeleton: React.FC = () => {
  return (
    <View style={styles.tradeCardContainer}>
      <View style={styles.tradeHeader}>
        <View style={styles.tradeStatus}>
          <SkeletonLoader width={8} height={8} borderRadius={4} />
          <SkeletonLoader width={100} height={14} style={{ marginLeft: 8 }} />
        </View>
        <SkeletonLoader width={60} height={12} />
      </View>
      
      <View style={styles.tradeInfo}>
        <View style={styles.tradeRow}>
          <SkeletonLoader width={80} height={16} />
          <SkeletonLoader width={100} height={16} />
        </View>
        <View style={styles.tradeRow}>
          <SkeletonLoader width={60} height={14} />
          <SkeletonLoader width={80} height={14} />
        </View>
      </View>
      
      <SkeletonLoader width="100%" height={36} borderRadius={8} style={{ marginTop: 12 }} />
    </View>
  );
};

const styles = StyleSheet.create({
  skeleton: {
    backgroundColor: '#E5E7EB',
  },
  cardContainer: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  userInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  userDetails: {
    marginLeft: 12,
  },
  cardContent: {
    marginBottom: 12,
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  tradeCardContainer: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  tradeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  tradeStatus: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tradeInfo: {
    marginBottom: 12,
  },
  tradeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
});