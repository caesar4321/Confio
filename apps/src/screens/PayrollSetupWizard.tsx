import React, { useState, useMemo, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, SafeAreaView, ScrollView, Alert, ActivityIndicator, FlatList, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useQuery, useMutation } from '@apollo/client';
import { GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';
import { CREATE_PAYROLL_RECIPIENT, SET_BUSINESS_DELEGATES_BY_EMPLOYEE } from '../apollo/mutations/payroll';
import { useAccount } from '../contexts/AccountContext';
import { useAlgorand } from '../hooks/useAlgorand';
import { biometricAuthService } from '../services/biometricAuthService';

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return 'Propietario';
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

export const PayrollSetupWizard = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const { signTransactions } = useAlgorand();
  const [step, setStep] = useState(1);
  const [selectedRecipients, setSelectedRecipients] = useState<Set<string>>(new Set());
  const [selectedDelegates, setSelectedDelegates] = useState<Set<string>>(new Set());
  const [activating, setActivating] = useState(false);

  const { data: employeesData, loading: employeesLoading } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    fetchPolicy: 'cache-and-network',
  });
  const [createRecipient] = useMutation(CREATE_PAYROLL_RECIPIENT);
  const [setBusinessDelegatesByEmployee] = useMutation(SET_BUSINESS_DELEGATES_BY_EMPLOYEE);

  const employees = useMemo(() => employeesData?.currentBusinessEmployees || [], [employeesData]);

  const toggleRecipient = useCallback((employeeId: string) => {
    setSelectedRecipients((prev) => {
      const next = new Set(prev);
      if (next.has(employeeId)) {
        next.delete(employeeId);
      } else {
        next.add(employeeId);
      }
      return next;
    });
  }, []);

  const toggleDelegate = useCallback((employeeId: string) => {
    setSelectedDelegates((prev) => {
      const next = new Set(prev);
      if (next.has(employeeId)) {
        next.delete(employeeId);
      } else {
        next.add(employeeId);
      }
      return next;
    });
  }, []);

  const handleNext = useCallback(() => {
    if (step === 1 && selectedRecipients.size === 0) {
      Alert.alert('Selecciona destinatarios', 'Debes seleccionar al menos un destinatario.');
      return;
    }
    if (step === 2 && selectedDelegates.size === 0) {
      Alert.alert('Selecciona delegados', 'Debes seleccionar al menos un delegado.');
      return;
    }
    setStep((prev) => prev + 1);
  }, [step, selectedRecipients.size, selectedDelegates.size]);

  const handleBack = useCallback(() => {
    if (step === 1) {
      navigation.goBack();
    } else {
      setStep((prev) => prev - 1);
    }
  }, [step, navigation]);

  const handleActivate = useCallback(async () => {
    const authMessage = 'Autoriza la activación de nómina';
    let ok = await biometricAuthService.authenticate(authMessage, true, true);
    if (!ok) {
      // Offer retry if authentication fails
      const shouldRetry = await new Promise<boolean>((resolve) => {
        Alert.alert(
          'Autenticación requerida',
          'Debes autenticarte para activar la nómina. Si fallaste varias veces, espera unos segundos antes de reintentar.',
          [
            { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
            { text: 'Reintentar', onPress: () => resolve(true) }
          ]
        );
      });

      if (shouldRetry) {
        ok = await biometricAuthService.authenticate(authMessage, true, true);
      }

      if (!ok) return;
    }

    try {
      setActivating(true);

      // Step 1: Create recipients
      const recipientPromises = Array.from(selectedRecipients).map(async (employeeId) => {
        const employee = employees.find((e: any) => e.id === employeeId);
        if (!employee?.user?.accounts) return;

        const account = employee.user.accounts.find((a: any) => a.accountType === 'personal');
        if (!account?.id) return;

        return createRecipient({
          variables: {
            recipientAccountId: account.id,
            displayName: `${employee.user?.firstName || ''} ${employee.user?.lastName || ''}`.trim() || employee.user?.username,
          },
        });
      });

      await Promise.all(recipientPromises);

      // Step 2: Activate payroll with delegates
      const businessAddress = activeAccount?.algorandAddress;
      if (!businessAddress) {
        throw new Error('Business account address not found');
      }

      const delegateEmployeeIds = Array.from(selectedDelegates);

      const { data } = await setBusinessDelegatesByEmployee({
        variables: {
          businessAccount: businessAddress,
          addEmployeeIds: delegateEmployeeIds,
          removeEmployeeIds: [],
        },
      });

      let res = data?.setBusinessDelegatesByEmployee;

      // If we got an unsigned transaction, we need to sign and submit it
      if (res?.unsignedTransactionB64) {
        const signedTxns = await signTransactions([res.unsignedTransactionB64]);
        if (!signedTxns || signedTxns.length === 0) {
          throw new Error('Failed to sign transaction');
        }

        // Submit the signed transaction
        const { data: submitData } = await setBusinessDelegatesByEmployee({
          variables: {
            businessAccount: businessAddress,
            addEmployeeIds: delegateEmployeeIds,
            removeEmployeeIds: [],
            signedTransaction: signedTxns[0],
          },
        });

        res = submitData?.setBusinessDelegatesByEmployee;
      }

      if (res?.success) {
        Alert.alert(
          '¡Nómina activada!',
          'Tu sistema de nómina está listo. Ahora puedes crear pagos y tus delegados podrán aprobarlos.',
          [
            {
              text: 'Ir a nómina',
              onPress: () => {
                navigation.reset({
                  index: 0,
                  routes: [{ name: 'BottomTabs', params: { screen: 'Employees' } }] as any,
                });
              },
            },
          ]
        );
      } else {
        Alert.alert('Error', res?.errors?.[0] || 'No se pudo activar nómina.');
      }
    } catch (e: any) {
      console.error('Activation error:', e);
      Alert.alert('Error', e?.message || 'No se pudo activar nómina.');
    } finally {
      setActivating(false);
    }
  }, [selectedRecipients, selectedDelegates, employees, activeAccount, setBusinessDelegatesByEmployee, createRecipient, navigation, signTransactions]);

  const renderStep1 = () => (
    <View style={styles.stepContent}>
      <View style={styles.stepHeader}>
        <Text style={styles.stepTitle}>¿A quién pagarás?</Text>
        <Text style={styles.stepSubtitle}>Selecciona empleados que recibirán nómina. Puedes agregar personas externas después.</Text>
      </View>

      {employeesLoading ? (
        <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={employees}
          keyExtractor={(item: any) => item.id}
          renderItem={({ item }) => {
            const name = `${item.user?.firstName || ''} ${item.user?.lastName || ''}`.trim() || item.user?.username || 'Empleado';
            const role = getRoleLabel(item.role || '');
            const isSelected = selectedRecipients.has(item.id);

            return (
              <TouchableOpacity
                style={[styles.listItem, isSelected && styles.listItemSelected]}
                onPress={() => toggleRecipient(item.id)}
                activeOpacity={0.7}
              >
                <View style={[styles.checkbox, isSelected && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                  {isSelected && <Icon name="check" size={16} color="#fff" />}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.listItemName}>{name}</Text>
                  <Text style={styles.listItemSubtext}>{role}</Text>
                </View>
              </TouchableOpacity>
            );
          }}
          contentContainerStyle={{ paddingBottom: 100 }}
        />
      )}

      <View style={styles.selectionCount}>
        <Text style={styles.selectionCountText}>
          {selectedRecipients.size} {selectedRecipients.size === 1 ? 'destinatario seleccionado' : 'destinatarios seleccionados'}
        </Text>
      </View>
    </View>
  );

  const renderStep2 = () => {
    const eligibleDelegates = employees.filter((e: any) => {
      const role = (e.role || '').toLowerCase();
      return role !== 'cashier';
    });

    return (
      <View style={styles.stepContent}>
        <View style={styles.stepHeader}>
          <Text style={styles.stepTitle}>¿Quién puede aprobar pagos?</Text>
          <Text style={styles.stepSubtitle}>Los delegados podrán aprobar y ejecutar pagos de nómina. Solo delega a personas de confianza.</Text>
        </View>

        <View style={styles.warningCard}>
          <Icon name="alert-triangle" size={18} color="#f59e0b" />
          <Text style={styles.warningCardText}>
            Los delegados tendrán poder para ejecutar pagos desde la bóveda de nómina.
          </Text>
        </View>

        <FlatList
          data={eligibleDelegates}
          keyExtractor={(item: any) => item.id}
          renderItem={({ item }) => {
            const name = `${item.user?.firstName || ''} ${item.user?.lastName || ''}`.trim() || item.user?.username || 'Empleado';
            const role = getRoleLabel(item.role || '');
            const isSelected = selectedDelegates.has(item.id);

            return (
              <TouchableOpacity
                style={[styles.listItem, isSelected && styles.listItemSelected]}
                onPress={() => toggleDelegate(item.id)}
                activeOpacity={0.7}
              >
                <View style={[styles.checkbox, isSelected && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                  {isSelected && <Icon name="check" size={16} color="#fff" />}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.listItemName}>{name}</Text>
                  <Text style={styles.listItemSubtext}>{role}</Text>
                </View>
              </TouchableOpacity>
            );
          }}
          contentContainerStyle={{ paddingBottom: 100 }}
        />

        <View style={styles.selectionCount}>
          <Text style={styles.selectionCountText}>
            {selectedDelegates.size} {selectedDelegates.size === 1 ? 'delegado seleccionado' : 'delegados seleccionados'}
          </Text>
        </View>
      </View>
    );
  };

  const renderStep3 = () => (
    <ScrollView style={styles.stepContent} contentContainerStyle={{ paddingBottom: 100 }}>
      <View style={styles.stepHeader}>
        <Text style={styles.stepTitle}>Todo listo para activar</Text>
        <Text style={styles.stepSubtitle}>Revisa la configuración antes de activar nómina.</Text>
      </View>

      <View style={styles.summaryCard}>
        <View style={styles.summaryRow}>
          <Icon name="users" size={20} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.summaryLabel}>Destinatarios</Text>
            <Text style={styles.summaryValue}>{selectedRecipients.size} personas recibirán nómina</Text>
          </View>
        </View>

        <View style={styles.summaryRow}>
          <Icon name="shield" size={20} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.summaryLabel}>Delegados</Text>
            <Text style={styles.summaryValue}>{selectedDelegates.size} personas pueden aprobar</Text>
          </View>
        </View>

        <View style={styles.summaryRow}>
          <Icon name="lock" size={20} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.summaryLabel}>Bóveda de nómina (cUSD)</Text>
            <Text style={styles.summaryValue}>Se creará automáticamente</Text>
          </View>
        </View>
      </View>

      <View style={styles.infoCard}>
        <Icon name="info" size={16} color={colors.muted} />
        <Text style={styles.infoCardText}>
          Al activar, se creará la delegación on-chain y la allowlist para que los delegados puedan firmar pagos desde la bóveda.
        </Text>
      </View>

      <TouchableOpacity
        style={[styles.activateButton, activating && styles.activateButtonDisabled]}
        onPress={handleActivate}
        disabled={activating}
      >
        {activating ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <>
            <Text style={styles.activateButtonText}>Activar nómina</Text>
            <Icon name="check" size={18} color="#fff" />
          </>
        )}
      </TouchableOpacity>
    </ScrollView>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack} style={styles.backButton}>
          <Icon name={step === 1 ? 'x' : 'chevron-left'} size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Configurar nómina</Text>
        <View style={{ width: 32 }} />
      </View>

      <View style={styles.progressBar}>
        <View style={[styles.progressSegment, step >= 1 && styles.progressSegmentActive]} />
        <View style={[styles.progressSegment, step >= 2 && styles.progressSegmentActive]} />
        <View style={[styles.progressSegment, step >= 3 && styles.progressSegmentActive]} />
      </View>

      <Text style={styles.progressText}>Paso {step} de 3</Text>

      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}

      {step < 3 && (
        <View style={styles.footer}>
          <TouchableOpacity
            style={[
              styles.nextButton,
              ((step === 1 && selectedRecipients.size === 0) ||
                (step === 2 && selectedDelegates.size === 0)) && { opacity: 0.5, backgroundColor: '#9ca3af' }
            ]}
            onPress={handleNext}
            disabled={
              (step === 1 && selectedRecipients.size === 0) ||
              (step === 2 && selectedDelegates.size === 0)
            }
          >
            <Text style={styles.nextButtonText}>Continuar</Text>
            <Icon name="arrow-right" size={18} color="#fff" />
          </TouchableOpacity>
        </View>
      )}
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
    marginTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 10 : 0,
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
  progressBar: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingTop: 16,
    gap: 8,
  },
  progressSegment: {
    flex: 1,
    height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
  },
  progressSegmentActive: {
    backgroundColor: colors.primary,
  },
  progressText: {
    textAlign: 'center',
    fontSize: 13,
    color: colors.muted,
    marginTop: 8,
    marginBottom: 16,
  },
  stepContent: {
    flex: 1,
    paddingHorizontal: 16,
  },
  stepHeader: {
    marginBottom: 20,
  },
  stepTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
  },
  stepSubtitle: {
    fontSize: 14,
    color: colors.muted,
    lineHeight: 20,
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 12,
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.border,
    marginBottom: 8,
    gap: 12,
  },
  listItemSelected: {
    borderColor: colors.primary,
    backgroundColor: '#ecfdf3',
  },
  checkbox: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fff',
  },
  listItemName: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
  listItemSubtext: {
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },
  warningText: {
    fontSize: 12,
    color: '#f59e0b',
    fontWeight: '600',
  },
  selectionCount: {
    position: 'absolute',
    bottom: 16,
    left: 16,
    right: 16,
    backgroundColor: '#fff',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.1,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: -2 },
    elevation: 4,
  },
  selectionCountText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  warningCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fffbeb',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#fcd34d',
    marginBottom: 16,
  },
  warningCardText: {
    flex: 1,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 18,
  },
  summaryCard: {
    backgroundColor: colors.bg,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 16,
    marginBottom: 16,
  },
  summaryRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  summaryLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 2,
  },
  summaryValue: {
    fontSize: 14,
    color: colors.muted,
  },
  infoCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    backgroundColor: colors.bg,
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 16,
  },
  infoCardText: {
    flex: 1,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  activateButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#065f46',
    paddingVertical: 14,
    borderRadius: 12,
    gap: 8,
    marginTop: 8,
  },
  activateButtonDisabled: {
    opacity: 0.6,
  },
  activateButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },
  footer: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: '#fff',
  },
  nextButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 14,
    borderRadius: 12,
    gap: 8,
  },
  nextButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },
});

export default PayrollSetupWizard;
