import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useQuery } from '@apollo/client';
import { GET_PENDING_PAYROLL_ITEMS } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';

type MenuItem = {
  key: string;
  title: string;
  description: string;
  icon: string;
  action: () => void;
};

export const DiscoverScreen = () => {
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { activeAccount } = useAccount();
  const isPersonalAccount = (activeAccount?.type || '').toLowerCase() === 'personal';
  const isBusinessAccount = (activeAccount?.type || '').toLowerCase() === 'business';
  const isEmployeeDelegate = !!activeAccount?.isEmployee;

  const { data: pendingPayrollData } = useQuery(GET_PENDING_PAYROLL_ITEMS, {
    skip: !activeAccount,
    fetchPolicy: 'cache-and-network',
  });
  const pendingPayrollCount = pendingPayrollData?.pendingPayrollItems?.length || 0;

  const MENU_ITEMS: MenuItem[] = useMemo(
    () => [
      {
        key: 'topup',
        title: 'Recarga dólares digitales',
        description: 'Compra dólares estables en minutos con métodos locales.',
        icon: 'dollar-sign',
        action: () => navigation.navigate('TopUp' as never),
      },
      {
        key: 'invite',
        title: 'Invita a tus amigos con tu usuario',
        description: 'Comparte tu @usuario y gana el equivalente a US$5 en $CONFIO por cada amigo que se una a Confío.',
        icon: 'user-plus',
        action: () => navigation.navigate('Achievements' as never),
      },
      {
        key: 'invest',
        title: 'Invierte en la app Confío',
        description: 'Explora la preventa y las oportunidades para ser parte del proyecto.',
        icon: 'trending-up',
        action: () => navigation.navigate('ConfioPresale' as never),
      },
      {
        key: 'deposit',
        title: 'Deposita USDC desde un exchange (avanzado)',
        description: 'Transfiere USDC desde Binance, Coinbase u otros exchanges compatibles.',
        icon: 'download-cloud',
        action: () => navigation.navigate('USDCDeposit' as never, { tokenType: 'usdc' } as never),
      },
      {
        key: 'payroll-manage',
        title: 'Gestionar nómina y asignar delegados',
        description: 'Configura delegados y destinatarios de nómina.',
        icon: 'briefcase',
        action: () => navigation.navigate(isBusinessAccount ? ('PayrollHome' as never) : ('CreateBusiness' as never)),
      },
    ],
    [navigation, isBusinessAccount]
  );

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.hero}>
        <View style={styles.heroIcon}>
          <Icon name="compass" size={28} color="#047857" />
        </View>
        <View style={styles.heroText}>
          <Text style={styles.heroTitle}>Acciones principales</Text>
          <Text style={styles.heroSubtitle}>Descubre los pasos esenciales para sacarle jugo a Confío.</Text>
        </View>
      </View>

      <Text style={styles.sectionLabel}>Tus próximos pasos</Text>
      {(isBusinessAccount || isEmployeeDelegate || isPersonalAccount) && pendingPayrollCount > 0 && (
        <TouchableOpacity
          style={styles.payrollCard}
          onPress={() => navigation.navigate('PayrollPending' as never)}
          activeOpacity={0.9}
        >
          <View style={styles.payrollIconWrap}>
            <Icon name="alert-triangle" size={20} color="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.payrollTitle}>Nómina pendiente</Text>
            <Text style={styles.payrollSubtitle}>Tienes {pendingPayrollCount} pagos para firmar</Text>
          </View>
          <Icon name="chevron-right" size={18} color="#9CA3AF" />
        </TouchableOpacity>
      )}
      <View style={styles.grid}>
        {MENU_ITEMS.map((item) => (
          <TouchableOpacity
            key={item.key}
            style={styles.card}
            onPress={item.action}
            activeOpacity={0.85}
          >
            <View style={styles.cardContent}>
              <View style={styles.cardIconWrap}>
                <Icon name={item.icon} size={22} color="#047857" />
              </View>
              <View style={styles.cardTextWrap}>
                <Text style={styles.cardTitle}>{item.title}</Text>
                <Text style={styles.cardDesc}>{item.description}</Text>
              </View>
            </View>
            <View style={styles.cardChevron}>
              <Icon name="chevron-right" size={18} color="#9CA3AF" />
            </View>
          </TouchableOpacity>
        ))}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F3F4F6' },
  content: { paddingHorizontal: 20, paddingTop: 24, paddingBottom: 32 },
  hero: {
    flexDirection: 'row',
    backgroundColor: '#ECFDF5',
    borderRadius: 20,
    padding: 20,
    marginBottom: 24,
  },
  heroIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  heroText: { flex: 1 },
  heroTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#065F46',
    marginBottom: 6,
  },
  heroSubtitle: {
    fontSize: 14,
    color: '#047857',
    lineHeight: 20,
  },
  sectionLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 12,
  },
  grid: { },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    paddingVertical: 18,
    paddingHorizontal: 16,
    marginBottom: 12,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 3,
  },
  cardContent: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  cardIconWrap: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: '#ECFDF5',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  cardTextWrap: { flex: 1 },
  cardTitle: { fontSize: 16, fontWeight: '700', color: '#111827', marginBottom: 4 },
  cardDesc: { fontSize: 13, color: '#6B7280', lineHeight: 18 },
  cardChevron: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#F9FAFB',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 12,
  },
  payrollCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#EEF2FF',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  payrollIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: '#8B5CF6',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  payrollTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#111827',
  },
  payrollSubtitle: {
    fontSize: 12,
    color: '#6B7280',
  },
});

export default DiscoverScreen;
