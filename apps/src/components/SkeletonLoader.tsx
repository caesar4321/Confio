import React, { useEffect, useRef } from 'react';
import { View, Animated, StyleSheet, ViewStyle } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';

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
  const shimmerValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.timing(shimmerValue, {
        toValue: 1,
        duration: 1500,
        useNativeDriver: true,
      })
    ).start();
  }, [shimmerValue]);

  const translateX = shimmerValue.interpolate({
    inputRange: [0, 1],
    outputRange: [-300, 300],
  });

  // Calculate actual dimensions
  const actualWidth = typeof width === 'number' ? width : 300; // Default width for percentage
  const actualHeight = height;

  return (
    <View
      style={[
        styles.container,
        {
          width,
          height,
          borderRadius,
          overflow: 'hidden',
          backgroundColor: '#e5e7eb',
        },
        style,
      ]}
    >
      <Animated.View
        style={[
          StyleSheet.absoluteFillObject,
          {
            transform: [{ translateX }],
          },
        ]}
      >
        <Svg
          width={actualWidth + 600} // Extra width for the shimmer
          height={actualHeight}
          style={StyleSheet.absoluteFillObject}
        >
          <Defs>
            <LinearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <Stop offset="0%" stopColor="#e5e7eb" stopOpacity="1" />
              <Stop offset="20%" stopColor="#f3f4f6" stopOpacity="1" />
              <Stop offset="50%" stopColor="#ffffff" stopOpacity="1" />
              <Stop offset="80%" stopColor="#f3f4f6" stopOpacity="1" />
              <Stop offset="100%" stopColor="#e5e7eb" stopOpacity="1" />
            </LinearGradient>
          </Defs>
          <Rect
            x="0"
            y="0"
            width={300}
            height="100%"
            fill="url(#grad)"
          />
        </Svg>
      </Animated.View>
    </View>
  );
};

export const WalletCardSkeleton: React.FC = () => (
  <View style={styles.walletCard}>
    <View style={styles.walletInfo}>
      <SkeletonLoader width={40} height={40} borderRadius={20} />
      <View style={styles.walletDetails}>
        <SkeletonLoader width={120} height={16} style={{ marginBottom: 4 }} />
        <SkeletonLoader width={60} height={14} />
      </View>
    </View>
    <SkeletonLoader width={80} height={20} />
  </View>
);

export const TransactionItemSkeleton: React.FC = () => (
  <View style={styles.transactionItem}>
    <SkeletonLoader width={40} height={40} borderRadius={20} />
    <View style={styles.transactionDetails}>
      <SkeletonLoader width={150} height={16} style={{ marginBottom: 4 }} />
      <SkeletonLoader width={100} height={14} />
    </View>
    <SkeletonLoader width={60} height={18} />
  </View>
);

export const OfferCardSkeleton: React.FC = () => (
  <View style={styles.offerCard}>
    <View style={styles.offerHeader}>
      <View style={styles.offerUserInfo}>
        <SkeletonLoader width={40} height={40} borderRadius={20} />
        <View style={styles.offerUserDetails}>
          <SkeletonLoader width={120} height={16} style={{ marginBottom: 4 }} />
          <SkeletonLoader width={80} height={14} />
        </View>
      </View>
      <SkeletonLoader width={60} height={20} />
    </View>
    <View style={styles.offerBody}>
      <SkeletonLoader width={100} height={14} style={{ marginBottom: 8 }} />
      <SkeletonLoader width="100%" height={16} style={{ marginBottom: 4 }} />
      <SkeletonLoader width="80%" height={14} />
    </View>
  </View>
);

export const TradeCardSkeleton: React.FC = () => (
  <View style={styles.tradeCard}>
    <View style={styles.tradeHeader}>
      <SkeletonLoader width={80} height={20} borderRadius={10} />
      <SkeletonLoader width={100} height={16} />
    </View>
    <View style={styles.tradeBody}>
      <View style={styles.tradeInfo}>
        <SkeletonLoader width={40} height={40} borderRadius={20} />
        <View style={styles.tradeDetails}>
          <SkeletonLoader width={150} height={16} style={{ marginBottom: 4 }} />
          <SkeletonLoader width={120} height={14} />
        </View>
      </View>
      <SkeletonLoader width={80} height={24} />
    </View>
  </View>
);

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#e5e7eb',
    overflow: 'hidden',
  },
  walletCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  walletInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletDetails: {
    marginLeft: 12,
  },
  transactionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    backgroundColor: '#fff',
    marginBottom: 8,
    borderRadius: 12,
  },
  transactionDetails: {
    flex: 1,
    marginLeft: 12,
  },
  offerCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  offerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  offerUserInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  offerUserDetails: {
    marginLeft: 12,
  },
  offerBody: {
    marginTop: 8,
  },
  tradeCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  tradeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  tradeBody: {
    marginTop: 8,
  },
  tradeInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  tradeDetails: {
    marginLeft: 12,
    flex: 1,
  },
});