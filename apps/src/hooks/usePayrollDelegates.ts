import { useCallback, useMemo, useState } from 'react';
import { useQuery, useMutation, gql } from '@apollo/client';
import { Alert } from 'react-native';
import algorandService from '../services/algorandService';
import { Buffer } from 'buffer';
import { useAccount } from '../contexts/AccountContext';

const GET_PAYROLL_DELEGATES = gql`
  query GetPayrollDelegates {
    payrollDelegates
  }
`;

const SET_BUSINESS_DELEGATES = gql`
  mutation SetBusinessDelegates($businessAccount: String!, $add: [String!]!, $remove: [String!]!, $signedTransaction: String) {
    setBusinessDelegates(businessAccount: $businessAccount, add: $add, remove: $remove, signedTransaction: $signedTransaction) {
      success
      errors
      unsignedTransactionB64
      transactionHash
    }
  }
`;

export const usePayrollDelegates = () => {
  const { activeAccount } = useAccount();
  const { data, loading, refetch } = useQuery(GET_PAYROLL_DELEGATES, {
    skip: !activeAccount || activeAccount.type !== 'business',
    fetchPolicy: 'cache-and-network',
  });
  const [mutateDelegates, { loading: mutating }] = useMutation(SET_BUSINESS_DELEGATES);
  const [activatedOverride, setActivatedOverride] = useState(false);

  const delegates = useMemo(() => (data?.payrollDelegates || []).map((d: string) => ({ address: d })), [data]);
  const isActivated = useMemo(() => delegates.length > 0 || activatedOverride, [delegates, activatedOverride]);

  const activatePayroll = useCallback(
    async (ownerAddress?: string) => {
      if (!activeAccount || activeAccount.type !== 'business') {
        Alert.alert('Solo negocios', 'Cambia a una cuenta de negocio para activar nómina.');
        return { success: false, error: 'Solo negocios' };
      }
      const businessAddr = activeAccount.algorandAddress || activeAccount.address;
      if (!businessAddr) {
        Alert.alert('Dirección faltante', 'No se encontró la dirección de la cuenta de negocio.');
        return { success: false, error: 'Dirección faltante' };
      }
      const adds = [businessAddr].concat(ownerAddress ? [ownerAddress] : []);
      try {
        // Step 1: ask server for unsigned txn
        const prepRes = await mutateDelegates({
          variables: { businessAccount: businessAddr, add: adds, remove: [], signedTransaction: null },
        });
        const unsignedB64 = prepRes.data?.setBusinessDelegates?.unsignedTransactionB64;
        if (!prepRes.data?.setBusinessDelegates?.success || !unsignedB64) {
          const msg = prepRes.data?.setBusinessDelegates?.errors?.[0] || 'No se pudo preparar la activación.';
          return { success: false, error: msg };
        }
        // Step 2: sign client-side
        const unsignedBytes = Uint8Array.from(Buffer.from(unsignedB64, 'base64'));
        const signedBytes = await algorandService.signTransactionBytes(unsignedBytes);
        const signedB64 = Buffer.from(signedBytes).toString('base64');
        // Step 3: submit
        const submitRes = await mutateDelegates({
          variables: { businessAccount: businessAddr, add: adds, remove: [], signedTransaction: signedB64 },
        });
        const submitData = submitRes.data?.setBusinessDelegates;
        const ok = submitData?.success;
        const txId = submitData?.transactionHash;
        if (!ok) {
          const msg = submitData?.errors?.[0] || 'No se pudo activar nómina.';
          return { success: false, error: msg };
        }
        await refetch();
        setActivatedOverride(true);
        return { success: true, txId };
      } catch (e: any) {
        console.error('activatePayroll error', e);
        return { success: false, error: e?.message || 'No se pudo activar nómina.' };
      }
    },
    [activeAccount, mutateDelegates, refetch],
  );

  return {
    delegates,
    loading: loading || mutating,
    isActivated,
    activatePayroll,
    refetch,
  };
};
