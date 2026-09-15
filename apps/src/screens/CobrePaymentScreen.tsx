import React from 'react';
import LocalPaymentScreen from './InfiniaPaymentScreen';
export default function CobrePaymentScreen({
  route,
}: {
  route?: {params?: {direction?: 'to_bank' | 'to_wallet'}};
}) {
  return <LocalPaymentScreen provider="cobre" route={route} />;
}
