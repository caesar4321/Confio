import React from 'react';
import { ScrollView, StyleSheet } from 'react-native';

type Props = React.PropsWithChildren;

/**
 * Scrollable body shared by the stock buy/sell success states.
 *
 * `flexGrow` fills taller phones without imposing a fixed height, while the
 * lack of vertical centering keeps the top reachable when large text or a
 * short viewport makes the receipt taller than the screen.
 */
export const StockTradeSuccessContent: React.FC<Props> = ({ children }) => (
  <ScrollView
    testID="stock-trade-success-scroll"
    style={styles.scroll}
    contentContainerStyle={styles.content}
    showsVerticalScrollIndicator={false}
  >
    {children}
  </ScrollView>
);

const styles = StyleSheet.create({
  scroll: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    alignItems: 'center',
    paddingHorizontal: 32,
    paddingTop: 16,
    paddingBottom: 32,
  },
});
