import React from 'react';
import { View, StyleSheet } from 'react-native';
import { ExchangeScreen } from './ExchangeScreen';

export const ExchangeContainer: React.FC = () => {
  return (
    <View style={styles.container}>
      <ExchangeScreen />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
}); 