// IA+ purchases through our own native module (ConfioBilling: StoreKit 2 on
// iOS, Play Billing 8 on Android). The store result is only a claim: the
// server verifies it with Apple/Google and decides entitlement. On iOS the
// transaction is finished only after the server has it.
import { NativeEventEmitter, NativeModules, Platform } from 'react-native';
import type { ApolloClient } from '@apollo/client';
import { VERIFY_CONFIO_IA_PURCHASE, type ConfioIaPlan } from './api';

const Native = NativeModules.ConfioBilling;
export const isBillingAvailable = !!Native;

export type StoreProduct = {
  productId: string;
  title: string;
  description: string;
  displayPrice: string;
  price: string;
  currency: string;
  period: string;
};

type StorePurchase = {
  platform: 'ios' | 'android';
  status?: 'purchased' | 'pending' | 'cancelled' | 'owned';
  productId?: string;
  transactionId?: string;
  signedTransaction?: string;
  purchaseToken?: string;
};

export type PurchaseOutcome =
  | { ok: true; plan: ConfioIaPlan }
  | { ok: false; reason: 'cancelled' | 'pending' | 'error'; message?: string };

export async function loadProduct(productId: string): Promise<StoreProduct | null> {
  if (!Native) {
    return null;
  }
  const products: StoreProduct[] = await Native.getProducts([productId]);
  return products.find((p) => p.productId === productId) ?? null;
}

async function verifyWithServer(client: ApolloClient<any>, purchase: StorePurchase) {
  const { data } = await client.mutate({
    mutation: VERIFY_CONFIO_IA_PURCHASE,
    variables: {
      platform: purchase.platform,
      signedTransaction: purchase.signedTransaction ?? null,
      purchaseToken: purchase.purchaseToken ?? null,
    },
  });
  const result = data?.verifyConfioIaPurchase;
  if (result?.success && purchase.transactionId) {
    await Native.finish(purchase.transactionId);
  }
  return result as { success: boolean; error?: string; plan?: ConfioIaPlan };
}

export async function buy(client: ApolloClient<any>, productId: string, billingToken: string): Promise<PurchaseOutcome> {
  if (!Native) {
    return { ok: false, reason: 'error', message: 'Las compras no están disponibles en esta versión.' };
  }
  // Android needs the product details loaded in this session before buying.
  await Native.getProducts([productId]);
  const purchase: StorePurchase = { platform: Platform.OS as 'ios' | 'android', ...(await Native.purchase(productId, billingToken)) };
  if (purchase.status === 'cancelled') {
    return { ok: false, reason: 'cancelled' };
  }
  if (purchase.status === 'pending') {
    return { ok: false, reason: 'pending', message: 'Tu pago está pendiente. Te avisaremos cuando se confirme.' };
  }
  if (purchase.status === 'owned') {
    return restore(client);
  }
  const result = await verifyWithServer(client, purchase);
  if (result?.success && result.plan?.isPlus) {
    return { ok: true, plan: result.plan };
  }
  return { ok: false, reason: 'error', message: result?.error || 'No pudimos confirmar tu compra.' };
}

export async function restore(client: ApolloClient<any>): Promise<PurchaseOutcome> {
  if (!Native) {
    return { ok: false, reason: 'error', message: 'Las compras no están disponibles en esta versión.' };
  }
  const purchases: StorePurchase[] = await Native.currentEntitlements();
  let last: { success: boolean; error?: string; plan?: ConfioIaPlan } | undefined;
  for (const purchase of purchases) {
    last = await verifyWithServer(client, { ...purchase, platform: Platform.OS as 'ios' | 'android' });
    if (last?.plan?.isPlus) {
      return { ok: true, plan: last.plan };
    }
  }
  return { ok: false, reason: 'error', message: last?.error || 'No encontramos una suscripción activa en esta cuenta de la tienda.' };
}

export function manageSubscriptions() {
  return Native?.manageSubscriptions?.();
}

// Renewals, purchases finished while the app was closed, and unfinished
// transactions: hand each to the server as it arrives.
export function listenForStoreTransactions(client: ApolloClient<any>, onPlan: (plan: ConfioIaPlan) => void) {
  if (!Native) {
    return () => {};
  }
  const emitter = new NativeEventEmitter(Native);
  const sub = emitter.addListener('ConfioBillingTransaction', async (purchase: StorePurchase) => {
    try {
      const result = await verifyWithServer(client, { ...purchase, platform: Platform.OS as 'ios' | 'android' });
      if (result?.plan) {
        onPlan(result.plan);
      }
    } catch {
      // Redelivered by the store until finished.
    }
  });
  return () => sub.remove();
}
