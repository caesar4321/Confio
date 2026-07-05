import React, { useMemo, useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, ActivityIndicator, Image, RefreshControl, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RECIPIENTS, GET_PAYROLL_VAULT_BALANCE, GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';
import { usePayrollDelegates } from '../hooks/usePayrollDelegates';
import { useAccount } from '../contexts/AccountContext';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { APP_LAYOUT } from '../config/layout';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

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
    } finally {
      setRefreshing(false);
    }
  }, [refetchDelegates, refetchEmployees, refetchVault, refetchRecipients]);

  const isBusinessAccount = activeAccount?.type === 'business';

  if (!isBusinessAccount) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Nómina"
          backgroundColor={colors.white}
          showBackButton
        />
        <View style={styles.centerContent}>
          <Icon name="briefcase" size={48} color={colors.muted} />
          <Text style={styles.emptyTitle}>Solo para cuentas de negocio</Text>
          <Text style={styles.emptySubtitle}>Cambia a tu cuenta de negocio para usar nómina.</Text>
        </View>
      </View>
    );
  }

  if (!isActivated) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Nómina"
          backgroundColor={colors.white}
          showBackButton
        />
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
          }
        >
          <View style={styles.heroCard}>
            <View style={styles.heroIcon}>
              <Icon name="dollar-sign" size={32} color={colors.white} />
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
              onPress={() => navigation.navigate('PayrollSetupWizard')}
            >
              <Text style={styles.primaryButtonText}>Activar nómina</Text>
              <Icon name="arrow-right" size={18} color={colors.white} />
            </TouchableOpacity>
          </View>
        </ScrollView>
      </View>
    );
  }

  // Activated state
  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Nómina"
        backgroundColor={colors.white}
        showBackButton
      />
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
      >
        {/* Vault balance — the hub's money hero sits on the brand field */}
        <View style={styles.vaultCard}>
          <BrandFieldBackground id="payrollVaultField" ringCy="25%" ringR={70} ringWidth={18} />
          <View style={styles.vaultInner}>
            <View style={styles.vaultHeader}>
              <Icon name="lock" size={16} color={colors.primaryLight} />
              <Text style={styles.vaultLabel}>BÓVEDA DE NÓMINA</Text>
            </View>
            {vaultLoading ? (
              <ActivityIndicator size="small" color={colors.white} />
            ) : (
              <View style={styles.balanceRow}>
                <Image source={require('../assets/png/cUSD.png')} style={styles.tokenLogo} />
                <Text style={styles.vaultBalance}>{vaultBalance.toFixed(2)}</Text>
                <Text style={styles.currencyLabel}>cUSD</Text>
              </View>
            )}
            <TouchableOpacity
              style={styles.vaultButton}
              onPress={() => navigation.navigate('PayrollTopUp')}
              accessibilityRole="button"
              accessibilityLabel="Agregar fondos a la bóveda"
            >
              <Icon name="plus" size={16} color={colors.white} />
              <Text style={styles.vaultButtonText}>Agregar fondos</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Main Action */}
        <TouchableOpacity
          style={styles.mainActionButton}
          onPress={() => navigation.navigate('PayrollRun')}
        >
          <View style={styles.mainActionIcon}>
            <Icon name="send" size={24} color={colors.white} />
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
            onPress={() => navigation.navigate('PayrollRecipientsManage')}
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
              <Icon name="chevron-right" size={14} color={colors.accent} />
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.statCard}
            onPress={() => navigation.navigate('PayrollDelegatesManage')}
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
              <Icon name="chevron-right" size={14} color={colors.accent} />
            </View>
          </TouchableOpacity>
        </View>

        {/* History */}
        <TouchableOpacity
          style={styles.historyButton}
          onPress={() => navigation.navigate('PayrollRunsHistory')}
        >
          <Icon name="clock" size={18} color={colors.muted} />
          <Text style={styles.historyText}>Historial de nóminas</Text>
          <Icon name="chevron-right" size={18} color={colors.muted} />
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.white },
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
    color: colors.textFlat,
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.muted,
    textAlign: 'center',
    marginTop: 8,
  },
  heroCard: {
    backgroundColor: colors.primarySoft,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.primaryLight,
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
    color: colors.textFlat,
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
    color: colors.textFlat,
    flex: 1,
  },
  primaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primaryDark,
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 12,
    gap: 8,
    width: '100%',
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.white,
  },
  vaultCard: {
    backgroundColor: colors.primary,
    borderRadius: 16,
    overflow: 'hidden',
  },
  vaultInner: {
    padding: 16,
  },
  vaultHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  vaultLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    color: colors.primaryLight,
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
    color: colors.white,
  },
  tokenLogo: {
    width: 28,
    height: 28,
    resizeMode: 'contain',
  },
  currencyLabel: {
    fontSize: 18,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.85)',
  },
  vaultButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 10,
  },
  vaultButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.white,
  },
  mainActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 16,
    borderRadius: 14,
    gap: 12,
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
    color: colors.white,
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
    backgroundColor: colors.white,
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: colors.border,
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
    color: colors.textFlat,
  },
  statLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textFlat,
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
    color: colors.accent,
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
    color: colors.textFlat,
  },
});

export default PayrollHomeScreen;
