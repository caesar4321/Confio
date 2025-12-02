import React, { useMemo, useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, SafeAreaView, ScrollView, ActivityIndicator, Image, RefreshControl } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RECIPIENTS, GET_PAYROLL_VAULT_BALANCE, GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';
import { usePayrollDelegates } from '../hooks/usePayrollDelegates';
import { useAccount } from '../contexts/AccountContext';

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

export const PayrollHomeScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const { data: vaultData, loading: vaultLoading, refetch: refetchVault } = useQuery(GET_PAYROLL_VAULT_BALANCE, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: recipientsData, loading: recipientsLoading, refetch: refetchRecipients } = useQuery(GET_PAYROLL_RECIPIENTS, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: employeesData, loading: employeesLoading, refetch: refetchEmployees } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    fetchPolicy: 'cache-and-network',
    pollInterval: 5000,
  });
  const { delegates, loading: delegatesLoading, isActivated, refetch: refetchDelegates } = usePayrollDelegates();
  const [refreshing, setRefreshing] = useState(false);

  useFocusEffect(
    useCallback(() => {
      console.log('[PayrollHome] Screen focused, refetching...');
      if (refetchEmployees) {
        refetchEmployees();
      }
      if (refetchDelegates) {
        refetchDelegates();
      }
      if (refetchVault) {
        refetchVault();
      }
    }, [refetchEmployees, refetchDelegates, refetchVault])
  );

  // Log delegates changes
  const delegateCount = useMemo(() => {
    const businessAddrUpper = (
      activeAccount?.algorandAddress ||
      (activeAccount as any)?.address ||
      (activeAccount as any)?.businessAddress ||
      (activeAccount as any)?.ownerAddress ||
      ''
    ).trim().toUpperCase();
    const unique = new Set<string>();
    (delegates || []).forEach((addr: string) => {
      const norm = addr?.trim?.().toUpperCase();
      if (norm && norm !== businessAddrUpper) unique.add(norm);
    });
    return unique.size;
  }, [delegates, activeAccount]);

  useEffect(() => {
    console.log('[PayrollHome] Delegates updated:', delegates);
    console.log('[PayrollHome] Active account address:', activeAccount?.algorandAddress);
    console.log('[PayrollHome] Filtered count (excluding business):', delegateCount);
  }, [delegates, activeAccount, delegateCount]);

  const recipients = useMemo(() => recipientsData?.payrollRecipients || [], [recipientsData]);
  const employees = useMemo(() => {
    const emps = employeesData?.currentBusinessEmployees || [];
    return emps;
  }, [employeesData]);
  const vaultBalance = useMemo(() => {
    const raw = vaultData?.payrollVaultBalance;
    const num = typeof raw === 'number' ? raw : parseFloat(raw || '0');
    return Number.isFinite(num) ? num : 0;
  }, [vaultData?.payrollVaultBalance]);

  const handleRefresh = useCallback(async () => {
    try {
      setRefreshing(true);
      await Promise.all([
        refetchEmployees?.(),
        refetchDelegates?.(),
        refetchVault?.(),
        refetchRecipients?.(),
      ]);
    } catch (e) {
      console.warn('[PayrollHome] Refresh failed', e);
    } finally {
      setRefreshing(false);
    }
  }, [refetchDelegates, refetchEmployees, refetchVault, refetchRecipients]);

  const isBusinessAccount = activeAccount?.type === 'business';

  if (!isBusinessAccount) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="chevron-left" size={24} color={colors.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Nómina</Text>
          <View style={{ width: 32 }} />
        </View>
        <View style={styles.centerContent}>
          <Icon name="briefcase" size={48} color={colors.muted} />
          <Text style={styles.emptyTitle}>Solo para cuentas de negocio</Text>
          <Text style={styles.emptySubtitle}>Cambia a tu cuenta de negocio para usar nómina.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!isActivated) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="chevron-left" size={24} color={colors.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Nómina</Text>
          <View style={{ width: 32 }} />
        </View>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
          }
        >
          <View style={styles.heroCard}>
            <View style={styles.heroIcon}>
              <Icon name="dollar-sign" size={32} color="#fff" />
            </View>
            <Text style={styles.heroTitle}>Nómina para tu negocio</Text>
            <Text style={styles.heroSubtitle}>
              Paga a tu equipo de forma automática con aprobación de delegados.
            </Text>
            <View style={styles.featureList}>
              <View style={styles.featureRow}>
                <Icon name="check-circle" size={18} color={colors.primary} />
                <Text style={styles.featureText}>Pagos programados y automáticos</Text>
              </View>
              <View style={styles.featureRow}>
                <Icon name="check-circle" size={18} color={colors.primary} />
                <Text style={styles.featureText}>Aprobación con firma de delegados</Text>
              </View>
              <View style={styles.featureRow}>
                <Icon name="check-circle" size={18} color={colors.primary} />
                <Text style={styles.featureText}>Historial transparente y auditable</Text>
              </View>
              <View style={styles.featureRow}>
                <Icon name="check-circle" size={18} color={colors.primary} />
                <Text style={styles.featureText}>Bóveda segura para fondos de nómina</Text>
              </View>
            </View>
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() => navigation.navigate('PayrollSetupWizard' as never)}
            >
              <Text style={styles.primaryButtonText}>Activar nómina</Text>
              <Icon name="arrow-right" size={18} color="#fff" />
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // Activated state
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Nómina</Text>
        <View style={{ width: 32 }} />
      </View>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
      >
        {/* Vault Balance Card */}
        <View style={styles.vaultCard}>
          <View style={styles.vaultHeader}>
            <Icon name="lock" size={20} color={colors.primary} />
            <Text style={styles.vaultLabel}>Bóveda de nómina</Text>
          </View>
          {vaultLoading ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <View style={styles.balanceRow}>
              <Image source={require('../assets/png/cUSD.png')} style={styles.tokenLogo} />
              <Text style={styles.vaultBalance}>{vaultBalance.toFixed(2)}</Text>
              <Text style={styles.currencyLabel}>cUSD</Text>
            </View>
          )}
          <TouchableOpacity
            style={styles.vaultButton}
            onPress={() => navigation.navigate('PayrollTopUp' as never)}
          >
            <Icon name="plus" size={16} color={colors.primary} />
            <Text style={styles.vaultButtonText}>Agregar fondos</Text>
          </TouchableOpacity>
        </View>

        {/* Main Action */}
        <TouchableOpacity
          style={styles.mainActionButton}
          onPress={() => navigation.navigate('PayrollRun' as never)}
        >
          <View style={styles.mainActionIcon}>
            <Icon name="send" size={24} color="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.mainActionTitle}>Crear nómina</Text>
            <Text style={styles.mainActionSubtitle}>Pagar ahora o programar</Text>
          </View>
          <Icon name="chevron-right" size={24} color={colors.muted} />
        </TouchableOpacity>

        {/* Quick Stats */}
        <View style={styles.statsGrid}>
          <TouchableOpacity
            style={styles.statCard}
            onPress={() => navigation.navigate('PayrollRecipientsManage' as never)}
          >
            <View style={styles.statHeader}>
              <Icon name="users" size={18} color={colors.primary} />
              <Text style={styles.statValue}>
                {recipientsLoading ? '...' : recipients.length}
              </Text>
            </View>
            <Text style={styles.statLabel}>Destinatarios</Text>
            <Text style={styles.statSubtext}>Empleados, contratistas...</Text>
            <View style={styles.statAction}>
              <Text style={styles.statActionText}>Gestionar</Text>
              <Icon name="chevron-right" size={14} color="#2563eb" />
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.statCard}
            onPress={() => navigation.navigate('PayrollDelegatesManage' as never)}
          >
            <View style={styles.statHeader}>
              <Icon name="shield" size={18} color={colors.primary} />
              <Text style={styles.statValue}>
                {delegatesLoading ? '...' : delegateCount}
              </Text>
            </View>
            <Text style={styles.statLabel}>Delegados</Text>
            <Text style={styles.statSubtext}>Pueden aprobar pagos</Text>
            <View style={styles.statAction}>
              <Text style={styles.statActionText}>Gestionar</Text>
              <Icon name="chevron-right" size={14} color="#2563eb" />
            </View>
          </TouchableOpacity>
        </View>

        {/* History */}
        <TouchableOpacity
          style={styles.historyButton}
          onPress={() => navigation.navigate('PayrollRunsHistory' as never)}
        >
          <Icon name="clock" size={18} color={colors.muted} />
          <Text style={styles.historyText}>Historial de nóminas</Text>
          <Icon name="chevron-right" size={18} color={colors.muted} />
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 18,
    color: colors.text,
    fontWeight: '600',
  },
  scrollContent: {
    padding: 16,
    gap: 16,
  },
  centerContent: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.muted,
    textAlign: 'center',
    marginTop: 8,
  },
  heroCard: {
    backgroundColor: '#ecfdf3',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#a7f3d0',
  },
  heroIcon: {
    width: 64,
    height: 64,
    borderRadius: 16,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  heroTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 8,
  },
  heroSubtitle: {
    fontSize: 15,
    color: colors.muted,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 22,
  },
  featureList: {
    width: '100%',
    gap: 12,
    marginBottom: 24,
  },
  featureRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  featureText: {
    fontSize: 14,
    color: colors.text,
    flex: 1,
  },
  primaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#065f46',
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 12,
    gap: 8,
    width: '100%',
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },
  vaultCard: {
    backgroundColor: colors.bg,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  vaultHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  vaultLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.muted,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
  },
  vaultBalance: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text,
  },
  tokenLogo: {
    width: 28,
    height: 28,
    resizeMode: 'contain',
  },
  currencyLabel: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.muted,
  },
  vaultButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: '#fff',
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  vaultButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primary,
  },
  mainActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 16,
    borderRadius: 14,
    gap: 12,
    shadowColor: '#000',
    shadowOpacity: 0.1,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  mainActionIcon: {
    width: 48,
    height: 48,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  mainActionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#fff',
  },
  mainActionSubtitle: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.8)',
    marginTop: 2,
  },
  statsGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOpacity: 0.03,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
  },
  statHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  statValue: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
  },
  statLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 2,
  },
  statSubtext: {
    fontSize: 11,
    color: colors.muted,
    marginBottom: 10,
  },
  statAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  statActionText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#2563eb',
  },
  historyButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: colors.bg,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  historyText: {
    flex: 1,
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
});

export default PayrollHomeScreen;
