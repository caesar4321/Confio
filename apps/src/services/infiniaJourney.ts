import {gql} from '@apollo/client';
export const INFINIA_OPTIONS = gql`
  query InfiniaJourneyOptions {
    infiniaJourneysEnabled
    myPaymentAccounts {
      internalId
      provider
      asset
      country
      status
      fundingInstructions {
        internalId
        kind
        status
      }
    }
    myPayoutDestinations {
      internalId
      provider
      asset
      country
      kind
      label
      holderName
      status
    }
  }
`;
export const INFINIA_HISTORY = gql`
  query InfiniaJourneyHistory($offset: Int!, $limit: Int!) {
    myInfiniaJourneys(offset: $offset, limit: $limit) {
      internalId
      direction
      stage
      failureCode
      bridgeId
      minimumFxOutput
      destinationSummary
      localAsset
      cryptoAccountId
      payoutAmount
      walletArrivalUnits
    }
  }
`;
export const INFINIA_DEPOSITS = gql`
  query InfiniaJourneyDeposits($account: UUID!, $offset: Int!) {
    infiniaJourneyDeposits(accountId: $account, offset: $offset) {
      internalId
      asset
      amount
      occurredAt
    }
  }
`;
const CREATE_JOURNEY = gql`
  mutation StartInfiniaJourney(
    $direction: String!
    $requestId: UUID!
    $localAccountId: UUID!
    $cryptoAccountId: UUID!
    $minimumFxOutput: Decimal!
    $bridgeId: UUID
    $creditId: UUID
    $destinationId: UUID
  ) {
    createInfiniaJourney(
      direction: $direction
      requestId: $requestId
      localAccountId: $localAccountId
      cryptoAccountId: $cryptoAccountId
      minimumFxOutput: $minimumFxOutput
      bridgeId: $bridgeId
      creditId: $creditId
      destinationId: $destinationId
    ) {
      success
      errors
      journey {
        internalId
        bridgeId
        stage
      }
    }
  }
`;
const ATTACH_BRIDGE = gql`
  mutation AttachInfiniaBridge($journeyId: UUID!, $bridgeId: UUID!) {
    attachInfiniaReturnBridge(journeyId: $journeyId, bridgeId: $bridgeId) {
      success
      errors
      journey {
        internalId
        bridgeId
        stage
      }
    }
  }
`;
export async function createInfiniaJourney(variables: Record<string, unknown>) {
  const {apolloClient} = await import('../apollo/client');
  const response = await apolloClient.mutate({
    mutation: CREATE_JOURNEY,
    variables,
  });
  const result = response.data?.createInfiniaJourney;
  if (!result?.success)
    throw new Error(result?.errors?.[0] || 'No se pudo preparar el pago');
  return result.journey;
}
export async function attachInfiniaBridge(journeyId: string, bridgeId: string) {
  const {apolloClient} = await import('../apollo/client');
  const response = await apolloClient.mutate({
    mutation: ATTACH_BRIDGE,
    variables: {journeyId, bridgeId},
  });
  const result = response.data?.attachInfiniaReturnBridge;
  if (!result?.success)
    throw new Error(result?.errors?.[0] || 'No se pudo vincular el envío');
  return result.journey;
}
export function infiniaStage(stage: string): string {
  return (
    (
      {
        awaiting_credit: 'Esperando acreditación',
        converting: 'Convirtiendo moneda',
        paying_out: 'Enviando pago',
        awaiting_wallet_delivery: 'Esperando tus dólares',
        awaiting_wallet_authorization: 'Dólares listos para traer a Confío',
        bridging: 'Envío a Confío en proceso',
        completed: 'Completado',
        failed: 'No completado',
        needs_review: 'Estamos revisando el pago. No lo repitas.',
      } as Record<string, string>
    )[stage] || 'Consultando estado'
  );
}
