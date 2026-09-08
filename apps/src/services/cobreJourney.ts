import {gql} from '@apollo/client';
export const COBRE_OPTIONS = gql`
  query CobreJourneyOptions {
    cobreJourneysEnabled
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
export const COBRE_HISTORY = gql`
  query CobreJourneyHistory($offset: Int!, $limit: Int!) {
    myCobreJourneys(offset: $offset, limit: $limit) {
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
export const COBRE_DEPOSITS = gql`
  query CobreJourneyDeposits($account: UUID!, $offset: Int!) {
    cobreJourneyDeposits(accountId: $account, offset: $offset) {
      internalId
      asset
      amount
      occurredAt
    }
  }
`;
const CREATE_JOURNEY = gql`
  mutation StartCobreJourney(
    $direction: String!
    $requestId: UUID!
    $localAccountId: UUID!
    $cryptoAccountId: UUID!
    $copcoAccountId: UUID!
    $minimumFxOutput: Decimal!
    $bridgeId: UUID
    $creditId: UUID
    $destinationId: UUID
  ) {
    createCobreJourney(
      direction: $direction
      requestId: $requestId
      localAccountId: $localAccountId
      cryptoAccountId: $cryptoAccountId
      copcoAccountId: $copcoAccountId
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
  mutation AttachCobreBridge($journeyId: UUID!, $bridgeId: UUID!) {
    attachCobreReturnBridge(journeyId: $journeyId, bridgeId: $bridgeId) {
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
export async function createCobreJourney(variables: Record<string, unknown>) {
  const {apolloClient} = await import('../apollo/client');
  const response = await apolloClient.mutate({
    mutation: CREATE_JOURNEY,
    variables,
  });
  const result = response.data?.createCobreJourney;
  if (!result?.success)
    throw new Error(result?.errors?.[0] || 'No se pudo preparar el pago');
  return result.journey;
}
export async function attachCobreBridge(journeyId: string, bridgeId: string) {
  const {apolloClient} = await import('../apollo/client');
  const response = await apolloClient.mutate({
    mutation: ATTACH_BRIDGE,
    variables: {journeyId, bridgeId},
  });
  const result = response.data?.attachCobreReturnBridge;
  if (!result?.success)
    throw new Error(result?.errors?.[0] || 'No se pudo vincular el envío');
  return result.journey;
}
export function cobreStage(stage: string): string {
  return (
    (
      {
        awaiting_credit: 'Esperando acreditación',
        converting: 'Convirtiendo moneda',
        converting_cop: 'Procesando conversión a pesos',
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
