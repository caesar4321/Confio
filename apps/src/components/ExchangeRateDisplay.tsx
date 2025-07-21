import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useSelectedCountryRate } from '../hooks/useExchangeRate';
import { colors } from '../config/theme';
import { useCountry } from '../contexts/CountryContext';
import { getCurrencyForCountry } from '../utils/currencyMapping';

interface ExchangeRateDisplayProps {
  style?: any;
  onPress?: () => void;
  showRefreshButton?: boolean;
  compact?: boolean;
}

export const ExchangeRateDisplay: React.FC<ExchangeRateDisplayProps> = ({
  style,
  onPress,
  showRefreshButton = false,
  compact = false
}) => {
  const { rate, loading, error, refetch, formatRate } = useSelectedCountryRate();
  const { selectedCountry } = useCountry();
  
  // Get currency information for the selected country
  const currencyCode = getCurrencyForCountry(selectedCountry);

  if (loading && !rate) {
    return (
      <View style={[styles.container, compact && styles.compactContainer, style]}>
        <View style={styles.loadingContainer}>
          <Icon name="loader" size={12} color={colors.text.secondary} />
          <Text style={[styles.loadingText, compact && styles.compactText]}>
            Cargando tasa...
          </Text>
        </View>
      </View>
    );
  }

  if (error && !rate) {
    return (
      <View style={[styles.container, compact && styles.compactContainer, style]}>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={12} color={colors.error} />
          <Text style={[styles.errorText, compact && styles.compactText]}>
            Error al cargar tasa
          </Text>
          {showRefreshButton && (
            <TouchableOpacity onPress={refetch} style={styles.refreshButton}>
              <Icon name="refresh-cw" size={12} color={colors.primary} />
            </TouchableOpacity>
          )}
        </View>
      </View>
    );
  }

  const handlePress = () => {
    if (onPress) {
      onPress();
    }
  };

  const containerStyle = [
    styles.container,
    compact && styles.compactContainer,
    onPress && styles.pressable,
    style
  ];

  return (
    <TouchableOpacity 
      style={containerStyle} 
      onPress={handlePress}
      disabled={!onPress}
      activeOpacity={onPress ? 0.7 : 1}
    >
      <View style={styles.rateContainer}>
        <Icon 
          name="trending-up" 
          size={compact ? 12 : 14} 
          color={colors.success} 
          style={styles.rateIcon} 
        />
        <Text style={[styles.rateLabel, compact && styles.compactText]}>
          Tasa actual:
        </Text>
        <Text style={[styles.rateValue, compact && styles.compactText]}>
          1 USD = {formatRate(2)} {currencyCode}
        </Text>
        {loading && (
          <Icon 
            name="loader" 
            size={compact ? 10 : 12} 
            color={colors.text.secondary} 
            style={styles.loadingIcon} 
          />
        )}
        {showRefreshButton && (
          <TouchableOpacity onPress={refetch} style={styles.refreshButton}>
            <Icon name="refresh-cw" size={compact ? 10 : 12} color={colors.primary} />
          </TouchableOpacity>
        )}
      </View>
      {!compact && (
        <Text style={styles.subtitle}>
          Tasa de referencia del mercado
        </Text>
      )}
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#F0FDF4',
    borderWidth: 1,
    borderColor: '#BBF7D0',
    borderRadius: 8,
    padding: 12,
  },
  compactContainer: {
    padding: 8,
    borderRadius: 6,
  },
  pressable: {
    // Add visual feedback for pressable items
  },
  rateContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  rateIcon: {
    marginRight: 6,
  },
  rateLabel: {
    fontSize: 12,
    color: '#065F46',
    marginRight: 4,
  },
  rateValue: {
    fontSize: 12,
    fontWeight: '600',
    color: '#065F46',
    flex: 1,
  },
  subtitle: {
    fontSize: 10,
    color: '#059669',
    marginTop: 4,
    fontStyle: 'italic',
  },
  loadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 12,
    color: colors.text.secondary,
    marginLeft: 6,
  },
  loadingIcon: {
    marginLeft: 6,
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  errorText: {
    fontSize: 12,
    color: colors.error,
    marginLeft: 6,
    flex: 1,
  },
  refreshButton: {
    padding: 4,
    marginLeft: 4,
  },
  compactText: {
    fontSize: 11,
  },
});