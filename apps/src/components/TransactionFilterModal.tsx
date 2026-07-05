import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  ScrollView,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

export interface TransactionFilters {
  types: {
    sent: boolean;
    received: boolean;
    payment: boolean;
    exchange: boolean;
    conversion: boolean;
    reward: boolean;
    presale: boolean;
    payroll: boolean;
    ramp: boolean;
    humanitarian: boolean;
  };
  currencies: {
    cUSD: boolean;
    CONFIO: boolean;
    USDC: boolean;
  };
  status: {
    completed: boolean;
    pending: boolean;
  };
  timeRange: 'all' | 'today' | 'week' | 'month' | 'year';
  amountRange: {
    min: string;
    max: string;
  };
}

interface TransactionFilterModalProps {
  visible: boolean;
  onClose: () => void;
  onApply: (filters: TransactionFilters) => void;
  currentFilters: TransactionFilters;
  theme?: {
    primary: string;
    secondary: string;
  };
}

const defaultTheme = {
  primary: colors.primary,
  secondary: colors.secondary,
};

export const TransactionFilterModal = ({
  visible,
  onClose,
  onApply,
  currentFilters,
  theme = defaultTheme,
}: TransactionFilterModalProps) => {
  const [filters, setFilters] = useState<TransactionFilters>(currentFilters);

  const handleReset = () => {
    const resetFilters: TransactionFilters = {
      types: {
        sent: true,
        received: true,
        payment: true,
        exchange: true,
        conversion: true,
        reward: true,
        presale: true,
        payroll: true,
        ramp: true,
        humanitarian: true,
      },
      currencies: {
        cUSD: true,
        CONFIO: true,
        USDC: true,
      },
      status: {
        completed: true,
        pending: true,
      },
      timeRange: 'all',
      amountRange: {
        min: '',
        max: '',
      },
    };
    setFilters(resetFilters);
  };

  const handleApply = () => {
    onApply(filters);
    onClose();
  };

  const toggleType = (type: keyof typeof filters.types) => {
    setFilters({
      ...filters,
      types: {
        ...filters.types,
        [type]: !filters.types[type],
      },
    });
  };

  const toggleCurrency = (currency: keyof typeof filters.currencies) => {
    setFilters({
      ...filters,
      currencies: {
        ...filters.currencies,
        [currency]: !filters.currencies[currency],
      },
    });
  };

  const toggleStatus = (status: keyof typeof filters.status) => {
    setFilters({
      ...filters,
      status: {
        ...filters.status,
        [status]: !filters.status[status],
      },
    });
  };

  const setTimeRange = (range: TransactionFilters['timeRange']) => {
    setFilters({
      ...filters,
      timeRange: range,
    });
  };

  const hasActiveFilters = () => {
    const allTypesSelected = Object.values(filters.types).every(v => v);
    const allCurrenciesSelected = Object.values(filters.currencies).every(v => v);
    const allStatusSelected = Object.values(filters.status).every(v => v);
    const noAmountRange = !filters.amountRange.min && !filters.amountRange.max;
    const allTimeRange = filters.timeRange === 'all';

    return !(allTypesSelected && allCurrenciesSelected && allStatusSelected && noAmountRange && allTimeRange);
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.modalOverlay}>
        <TouchableOpacity
          style={styles.modalBackdrop}
          activeOpacity={1}
          onPress={onClose}
        />
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Filtrar transacciones</Text>
            <TouchableOpacity onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.text.secondary} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.filterSections} showsVerticalScrollIndicator={false}>
            {/* Transaction Types */}
            <View style={styles.filterSection}>
              <Text style={styles.sectionTitle}>Tipo de transacción</Text>
              <View style={styles.filterOptions}>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.sent && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleType('sent')}
                >
                  <Icon name="arrow-up" size={16} color={filters.types.sent ? theme.primary : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.sent && { color: theme.primary }]}>
                    Enviado
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.received && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleType('received')}
                >
                  <Icon name="arrow-down" size={16} color={filters.types.received ? theme.primary : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.received && { color: theme.primary }]}>
                    Recibido
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.payment && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleType('payment')}
                >
                  <Icon name="shopping-bag" size={16} color={filters.types.payment ? theme.primary : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.payment && { color: theme.primary }]}>
                    Pago
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.exchange && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleType('exchange')}
                >
                  <Icon name="refresh-cw" size={16} color={filters.types.exchange ? theme.primary : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.exchange && { color: theme.primary }]}>
                    Intercambio
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.conversion && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleType('conversion')}
                >
                  <Icon name="repeat" size={16} color={filters.types.conversion ? theme.primary : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.conversion && { color: theme.primary }]}>
                    Conversión
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.reward && { backgroundColor: '#FBBF24' + '20', borderColor: '#FBBF24' }
                  ]}
                  onPress={() => toggleType('reward')}
                >
                  <Icon name="gift" size={16} color={filters.types.reward ? colors.offRampIcon : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.reward && { color: colors.offRampIcon }]}>
                    Recompensa
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.presale && { backgroundColor: '#6366F1' + '20', borderColor: '#6366F1' }
                  ]}
                  onPress={() => toggleType('presale')}
                >
                  <Icon name="lock" size={16} color={filters.types.presale ? '#6366F1' : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.presale && { color: '#6366F1' }]}>
                    Preventa
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.payroll && { backgroundColor: colors.primaryDark + '20', borderColor: colors.primaryDark }
                  ]}
                  onPress={() => toggleType('payroll')}
                >
                  <Icon name="briefcase" size={16} color={filters.types.payroll ? colors.primaryDark : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.payroll && { color: colors.primaryDark }]}>
                    Nómina
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.ramp && { backgroundColor: '#0EA5E9' + '20', borderColor: '#0EA5E9' }
                  ]}
                  onPress={() => toggleType('ramp')}
                >
                  <Icon name="download-cloud" size={16} color={filters.types.ramp ? '#0EA5E9' : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.ramp && { color: '#0EA5E9' }]}>
                    Recarga/retiro
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.types.humanitarian && { backgroundColor: '#E11D48' + '20', borderColor: '#E11D48' }
                  ]}
                  onPress={() => toggleType('humanitarian')}
                >
                  <Icon name="heart" size={16} color={filters.types.humanitarian ? '#E11D48' : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.types.humanitarian && { color: '#E11D48' }]}>
                    Ayuda humanitaria
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Currencies */}
            <View style={styles.filterSection}>
              <Text style={styles.sectionTitle}>Moneda</Text>
              <View style={styles.filterOptions}>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.currencies.cUSD && { backgroundColor: theme.primary + '20', borderColor: theme.primary }
                  ]}
                  onPress={() => toggleCurrency('cUSD')}
                >
                  <Text style={[styles.filterChipText, filters.currencies.cUSD && { color: theme.primary }]}>
                    cUSD
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.currencies.CONFIO && { backgroundColor: theme.secondary + '20', borderColor: theme.secondary }
                  ]}
                  onPress={() => toggleCurrency('CONFIO')}
                >
                  <Text style={[styles.filterChipText, filters.currencies.CONFIO && { color: theme.secondary }]}>
                    CONFIO
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.currencies.USDC && { backgroundColor: colors.accent + '20', borderColor: colors.accent }
                  ]}
                  onPress={() => toggleCurrency('USDC')}
                >
                  <Text style={[styles.filterChipText, filters.currencies.USDC && { color: colors.accent }]}>
                    USDC
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Status */}
            <View style={styles.filterSection}>
              <Text style={styles.sectionTitle}>Estado</Text>
              <View style={styles.filterOptions}>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.status.completed && { backgroundColor: colors.primaryDark + '20', borderColor: colors.primaryDark }
                  ]}
                  onPress={() => toggleStatus('completed')}
                >
                  <Icon name="check-circle" size={16} color={filters.status.completed ? colors.primaryDark : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.status.completed && { color: colors.primaryDark }]}>
                    Completado
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.filterChip,
                    filters.status.pending && { backgroundColor: colors.offRampIcon + '20', borderColor: colors.offRampIcon }
                  ]}
                  onPress={() => toggleStatus('pending')}
                >
                  <Icon name="clock" size={16} color={filters.status.pending ? colors.offRampIcon : colors.text.secondary} />
                  <Text style={[styles.filterChipText, filters.status.pending && { color: colors.offRampIcon }]}>
                    Pendiente
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Time Range */}
            <View style={styles.filterSection}>
              <Text style={styles.sectionTitle}>Período</Text>
              <View style={styles.filterOptions}>
                {[
                  { value: 'all', label: 'Todo' },
                  { value: 'today', label: 'Hoy' },
                  { value: 'week', label: 'Esta semana' },
                  { value: 'month', label: 'Este mes' },
                  { value: 'year', label: 'Este año' },
                ].map((option) => (
                  <TouchableOpacity
                    key={option.value}
                    style={[
                      styles.filterChip,
                      filters.timeRange === option.value && {
                        backgroundColor: theme.primary + '20',
                        borderColor: theme.primary
                      }
                    ]}
                    onPress={() => setTimeRange(option.value as TransactionFilters['timeRange'])}
                  >
                    <Text style={[
                      styles.filterChipText,
                      filters.timeRange === option.value && { color: theme.primary }
                    ]}>
                      {option.label}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          </ScrollView>

          <View style={styles.modalFooter}>
            <TouchableOpacity
              style={styles.resetButton}
              onPress={handleReset}
            >
              <Text style={styles.resetButtonText}>Restablecer</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.applyButton, { backgroundColor: theme.primary }]}
              onPress={handleApply}
            >
              <Text style={styles.applyButtonText}>
                Aplicar filtros {hasActiveFilters() && '•'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 24,
    paddingBottom: Platform.OS === 'ios' ? 34 : 24,
    maxHeight: '80%',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: -4 },
        shadowOpacity: 0.1,
        shadowRadius: 8,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    marginBottom: 24,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  filterSections: {
    paddingHorizontal: 24,
  },
  filterSection: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 12,
  },
  filterOptions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  filterChip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.neutral,
    marginBottom: 8,
    marginRight: 8,
  },
  filterChipText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.secondary,
    marginLeft: 6,
  },
  modalFooter: {
    flexDirection: 'row',
    paddingHorizontal: 24,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 12,
  },
  resetButton: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  resetButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  applyButton: {
    flex: 2,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  applyButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.white,
  },
});
