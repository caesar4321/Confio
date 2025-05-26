import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

export const ExchangeScreen = () => {
  const [fromAmount, setFromAmount] = useState('');
  const [toAmount, setToAmount] = useState('');

  // Mock data
  const currencies = [
    { code: 'USD', name: 'US Dollar', rate: 1 },
    { code: 'EUR', name: 'Euro', rate: 0.92 },
    { code: 'GBP', name: 'British Pound', rate: 0.79 },
    { code: 'JPY', name: 'Japanese Yen', rate: 151.62 },
    { code: 'MXN', name: 'Mexican Peso', rate: 16.65 },
  ];

  const handleSwap = () => {
    // Implement currency swap logic
  };

  return (
    <View style={styles.container}>
      <ScrollView style={styles.content}>
        {/* From Currency */}
        <View style={styles.currencyCard}>
          <Text style={styles.label}>De</Text>
          <View style={styles.currencyInput}>
            <TextInput
              style={styles.amountInput}
              placeholder="0.00"
              keyboardType="decimal-pad"
              value={fromAmount}
              onChangeText={setFromAmount}
            />
            <TouchableOpacity style={styles.currencySelector}>
              <Text style={styles.currencyCode}>USD</Text>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.balance}>Balance: $1,234.56</Text>
        </View>

        {/* Swap Button */}
        <TouchableOpacity style={styles.swapButton} onPress={handleSwap}>
          <Icon name="repeat" size={24} color="#FFFFFF" />
        </TouchableOpacity>

        {/* To Currency */}
        <View style={styles.currencyCard}>
          <Text style={styles.label}>A</Text>
          <View style={styles.currencyInput}>
            <TextInput
              style={styles.amountInput}
              placeholder="0.00"
              keyboardType="decimal-pad"
              value={toAmount}
              onChangeText={setToAmount}
            />
            <TouchableOpacity style={styles.currencySelector}>
              <Text style={styles.currencyCode}>EUR</Text>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.balance}>Balance: €987.65</Text>
        </View>

        {/* Exchange Rate */}
        <View style={styles.rateCard}>
          <Text style={styles.rateLabel}>Tasa de cambio</Text>
          <Text style={styles.rateValue}>1 USD = 0.92 EUR</Text>
        </View>

        {/* Exchange Button */}
        <TouchableOpacity style={styles.exchangeButton}>
          <Text style={styles.exchangeButtonText}>Intercambiar</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F3F4F6',
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
  },
  currencyCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  label: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 8,
  },
  currencyInput: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  amountInput: {
    flex: 1,
    fontSize: 24,
    fontWeight: '500',
    color: '#1F2937',
  },
  currencySelector: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  currencyCode: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginRight: 4,
  },
  balance: {
    fontSize: 14,
    color: '#6B7280',
  },
  swapButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#72D9BC',
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
    marginVertical: 8,
  },
  rateCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    alignItems: 'center',
  },
  rateLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 4,
  },
  rateValue: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  exchangeButton: {
    backgroundColor: '#72D9BC',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  exchangeButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#FFFFFF',
  },
}); 