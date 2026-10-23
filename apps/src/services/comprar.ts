// Comprar (marketplace) — the client half of marketplace/escrow.py and the
// ConfioMarketEscrow contract.
//
// Every order action is a server-built sponsored 7702 batch, the same
// prepare → sign → submit shape as inviteBsc.ts. The client can only sign or
// not sign; it never builds or substitutes calldata. Money states come from
// the server's chain mirror, never from a receipt seen here.
//
//   deposit  buyer     pay into the escrow (prepareMarketOrder builds it)
//   ship     merchant  mark shipped (opens the auto-release window)
//   confirm  buyer     "lo recibí" — pays the merchant now
//   dispute  buyer     freezes auto-release; Confío decides refund or release
//   refund   merchant  give the money back (cancel or return)
//   reclaim  buyer     take back an order the store never marked shipped

import { gql } from '@apollo/client';
import {
  BatchCall,
  BscRevertedError,
  bscGetNonce,
  hashBatchIntent,
  signIntentDigest,
  signSetCodeAuthorization,
} from './evmWallet';
import { delegateNonce, fetchSponsored7702Params, isDelegatedTo } from './sponsored7702';

export type MarketAction = 'deposit' | 'ship' | 'confirm' | 'dispute' | 'refund' | 'reclaim';

const STORE_FIELDS = `
  id name description countryCode city shipsOutsideCity status isOpen
  avgRating ratingCount completedOrders ownerDisplayName
`;

const PRODUCT_FIELDS = `
  id title description category priceLocal currencyCode stock photoUrls status
  rejectionReason isBuyable
`;

export const ORDER_FIELDS = `
  id role status pendingAction productId productTitle productPhotoUrl quantity
  unitPriceLocal subtotalLocal currencyCode amountUsd feeUsd merchantNetUsd
  deliveryCity deliveryCountry deliveryOutsideCity deliveryEstimateLocal
  deliveryAddress deliveryPhone deliveryNote buyerDisplayName trackingReference
  shipBy releaseAt disputedAt createdAt settledAt availableActions rating lastTxHash
  store { ${STORE_FIELDS} }
`;

export const GET_MARKETPLACE_HOME = gql`
  query MarketplaceHome($countryCode: String!, $city: String!) {
    marketplaceCategories { key label }
    marketplaceCity(countryCode: $countryCode, city: $city) {
      countryCode city currencyCode isLive deliveryEstimate deliveryPartner storeCount
    }
  }
`;

export const LOCATE_MARKETPLACE_CITY = gql`
  mutation LocateMarketplaceCity($latitude: Float!, $longitude: Float!, $accuracy: Float) {
    locateMarketplaceCity(latitude: $latitude, longitude: $longitude, accuracy: $accuracy) {
      city { countryCode city isLive }
    }
  }
`;

export const GET_MARKETPLACE_CITIES = gql`
  query MarketplaceCities($countryCode: String!) {
    marketplaceCities(countryCode: $countryCode) {
      countryCode city currencyCode isLive deliveryEstimate storeCount
    }
    marketplaceCountries { countryCode storeCount }
  }
`;

export const GET_MARKETPLACE_PRODUCTS = gql`
  query MarketplaceProducts($countryCode: String!, $city: String, $category: String,
                            $search: String, $storeId: ID, $limit: Int, $offset: Int) {
    marketplaceProducts(countryCode: $countryCode, city: $city, category: $category,
                        search: $search, storeId: $storeId, limit: $limit, offset: $offset) {
      ${PRODUCT_FIELDS}
      store { id name city countryCode avgRating ratingCount }
    }
  }
`;

export const GET_MARKETPLACE_PRODUCT = gql`
  query MarketplaceProduct($id: ID!) {
    marketplaceProduct(id: $id) {
      ${PRODUCT_FIELDS}
      store { ${STORE_FIELDS} }
    }
  }
`;

export const GET_CHECKOUT_QUOTE = gql`
  query MarketCheckoutQuote($productId: ID!, $quantity: Int!, $deliveryCountry: String!, $deliveryCity: String!) {
    marketCheckoutQuote(productId: $productId, quantity: $quantity,
                        deliveryCountry: $deliveryCountry, deliveryCity: $deliveryCity) {
      subtotalLocal currencyCode fxRate amountUsd outsideCity shipsOutsideCity
      deliveryEstimateLocal deliveryPartner
    }
  }
`;

export const GET_MY_MARKET_ORDERS = gql`
  query MyMarketOrders($role: String, $limit: Int, $offset: Int) {
    myMarketOrders(role: $role, limit: $limit, offset: $offset) { ${ORDER_FIELDS} }
  }
`;

export const GET_MARKET_ORDER = gql`
  query MarketOrder($id: ID!) {
    marketOrder(id: $id) { ${ORDER_FIELDS} }
  }
`;

export const GET_MY_MARKET_STORE = gql`
  query MyMarketStore {
    myMarketStore { ${STORE_FIELDS} }
    myMarketStoreProducts { ${PRODUCT_FIELDS} stockRevision }
    marketplaceCategories { key label }
  }
`;

export const SUBMIT_MARKETPLACE_INTEREST = gql`
  mutation SubmitMarketplaceInterest($countryCode: String!, $city: String!, $role: String!,
                                     $categories: [String], $wants: String, $priceRange: String,
                                     $monthlySales: String, $channels: [String], $notify: Boolean) {
    submitMarketplaceInterest(countryCode: $countryCode, city: $city, role: $role,
                              categories: $categories, wants: $wants, priceRange: $priceRange,
                              monthlySales: $monthlySales, channels: $channels, notify: $notify) {
      success error
    }
  }
`;

export const OPEN_MARKET_STORE = gql`
  mutation OpenMarketStore($name: String!, $description: String, $countryCode: String!,
                           $city: String!, $shipsOutsideCity: Boolean) {
    openMarketStore(name: $name, description: $description, countryCode: $countryCode,
                    city: $city, shipsOutsideCity: $shipsOutsideCity) {
      success error store { ${STORE_FIELDS} }
    }
  }
`;

export const UPDATE_MARKET_STORE = gql`
  mutation UpdateMarketStore($name: String, $description: String, $shipsOutsideCity: Boolean, $paused: Boolean) {
    updateMarketStore(name: $name, description: $description, shipsOutsideCity: $shipsOutsideCity, paused: $paused) {
      success error store { ${STORE_FIELDS} }
    }
  }
`;

export const REQUEST_MARKET_PHOTO_UPLOAD = gql`
  mutation RequestMarketPhotoUpload($contentType: String!) {
    requestMarketPhotoUpload(contentType: $contentType) {
      success error upload { url key method fields expiresIn }
    }
  }
`;

export const SAVE_MARKET_PRODUCT = gql`
  mutation SaveMarketProduct($productId: ID, $title: String!, $description: String,
                             $category: String!, $priceLocal: String!, $stock: Int!,
                             $expectedStock: Int, $expectedStockRevision: Int, $photoKeys: [String]) {
    saveMarketProduct(productId: $productId, title: $title, description: $description,
                      category: $category, priceLocal: $priceLocal, stock: $stock,
                      expectedStock: $expectedStock, expectedStockRevision: $expectedStockRevision,
                      photoKeys: $photoKeys) {
      success error product { ${PRODUCT_FIELDS} }
    }
  }
`;

export const SET_MARKET_PRODUCT_PAUSED = gql`
  mutation SetMarketProductPaused($productId: ID!, $paused: Boolean!) {
    setMarketProductPaused(productId: $productId, paused: $paused) { success error }
  }
`;

export const DELETE_MARKET_PRODUCT = gql`
  mutation DeleteMarketProduct($productId: ID!) {
    deleteMarketProduct(productId: $productId) { success error }
  }
`;

export const SET_MARKET_ORDER_TRACKING = gql`
  mutation SetMarketOrderTracking($orderId: ID!, $trackingReference: String!) {
    setMarketOrderTracking(orderId: $orderId, trackingReference: $trackingReference) { success error }
  }
`;

export const RATE_MARKET_ORDER = gql`
  mutation RateMarketOrder($orderId: ID!, $rating: Int!, $comment: String) {
    rateMarketOrder(orderId: $orderId, rating: $rating, comment: $comment) { success error }
  }
`;

const PREPARE_ORDER = gql`
  mutation PrepareMarketOrder($productId: ID!, $quantity: Int!, $deliveryCountry: String!,
                              $deliveryCity: String!, $deliveryAddress: String!,
                              $deliveryPhone: String!, $deliveryNote: String, $outsideCityAck: Boolean) {
    prepareMarketOrder(productId: $productId, quantity: $quantity, deliveryCountry: $deliveryCountry,
                       deliveryCity: $deliveryCity, deliveryAddress: $deliveryAddress,
                       deliveryPhone: $deliveryPhone, deliveryNote: $deliveryNote,
                       outsideCityAck: $outsideCityAck) {
      success error order { ${ORDER_FIELDS} } calls { to valueWei data } intentId
    }
  }
`;

const ACTION_CALLS = gql`
  mutation MarketOrderActionCalls($orderId: ID!, $action: String!) {
    marketOrderActionCalls(orderId: $orderId, action: $action) {
      success error calls { to valueWei data } intentId
    }
  }
`;

const SUBMIT_ACTION = gql`
  mutation SubmitMarketOrderAction($orderId: ID!, $action: String!, $nonce: String!, $deadline: String!,
                                   $intentSignature: String!, $authorization: MarketAuthorizationInput,
                                   $disputeReason: String) {
    submitMarketOrderAction(orderId: $orderId, action: $action, nonce: $nonce, deadline: $deadline,
                            intentSignature: $intentSignature, authorization: $authorization,
                            disputeReason: $disputeReason) {
      success error authorizationRequired transactionHash
    }
  }
`;

/** A failure whose outcome is UNKNOWN (network error after the order exists):
 *  the payment may be on its way. The UI must open the order, never retry. */
export class MarketOutcomeUnknownError extends Error {
  orderId: string;
  constructor(orderId: string, cause?: string) {
    super(cause || 'outcome_unknown');
    this.orderId = orderId;
  }
}

/** Stable error codes → Spanish copy. Unknown codes fall back to a generic line. */
export const COMPRAR_ERRORS: Record<string, string> = {
  marketplace_disabled: 'Comprar está en preparación. Inténtalo más tarde.',
  sponsored_rail_unavailable: 'Comprar está en preparación. Inténtalo más tarde.',
  permission_denied: 'Tu rol en este negocio no permite esta acción.',
  account_not_found: 'No encontramos tu cuenta. Vuelve a intentarlo.',
  limits_unavailable: 'Comprar no está disponible en este momento. Inténtalo en un momento.',
  marketplace_busy: 'Comprar está muy solicitado ahora. Inténtalo en unos minutos.',
  identity_required: 'Verifica tu identidad para comprar y vender en Confío.',
  product_unavailable: 'Este producto ya no está disponible.',
  own_store: 'No puedes comprar en tu propia tienda.',
  city_not_live: 'Esta tienda todavía no vende en Confío.',
  out_of_stock: 'No queda stock suficiente.',
  bad_quantity: 'La cantidad no es válida.',
  delivery_address_required: 'Escribe la dirección de entrega.',
  delivery_phone_required: 'Escribe un teléfono para el repartidor.',
  store_city_only: 'Esta tienda solo entrega en su ciudad.',
  outside_city_ack_required: 'Confirma que el envío a otra ciudad cuesta más.',
  order_too_large: 'Este pedido supera el máximo por compra.',
  rate_unavailable: 'No pudimos calcular el precio en dólares. Inténtalo en un momento.',
  rate_stale: 'No pudimos calcular el precio en dólares. Inténtalo en un momento.',
  insufficient_balance: 'Saldo insuficiente.',
  redeem_below_minimum: 'Necesitas al menos US$1 disponible para completar el pago.',
  balance_unavailable: 'No pudimos leer tu saldo. Inténtalo de nuevo.',
  no_bsc_address: 'Tu cuenta aún se está activando. Inténtalo en un momento.',
  store_cannot_receive: 'Esta tienda no puede recibir pagos ahora.',
  order_not_payable: 'Este pedido ya no se puede pagar. Vuelve a intentarlo desde el producto.',
  action_not_allowed: 'Esta acción ya no está disponible para el pedido.',
  action_in_progress: 'Ya hay una acción en curso para este pedido. Espera unos segundos.',
  not_your_order: 'Este pedido no es tuyo.',
  order_not_found: 'No encontramos el pedido.',
  dispute_reason_required: 'Cuéntanos qué pasó (al menos 10 caracteres).',
  authorization_expired: 'El pago expiró. Vuelve a intentarlo desde el producto.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
  gas_price_too_high: 'La red está congestionada. Inténtalo de nuevo en unos minutos.',
  simulation_reverted: 'No se pudo completar en la red. Inténtalo de nuevo.',
  store_exists: 'Ya tienes una tienda.',
  no_store: 'Primero abre tu tienda.',
  bad_name: 'El nombre debe tener entre 2 y 80 caracteres.',
  bad_title: 'El título debe tener entre 3 y 100 caracteres.',
  bad_price: 'El precio no es válido.',
  bad_stock: 'El stock no es válido.',
  bad_category: 'Elige una categoría.',
  photo_required: 'Agrega al menos una foto del producto.',
  bad_photo: 'Una de las fotos no es válida. Vuelve a subirla.',
  too_many_uploads: 'Demasiadas subidas seguidas. Espera un rato e inténtalo de nuevo.',
  already_rated: 'Ya calificaste este pedido.',
  payment_in_progress: 'Ya tienes un pago en curso para este producto. Revisa Mis compras.',
  stale_form: 'El producto cambió. Vuelve a abrirlo para editarlo.',
  price_not_confirmed: 'Compra cancelada: el precio cambió.',
};

export const comprarError = (code?: string | null): string =>
  (code && COMPRAR_ERRORS[code]) || 'Algo salió mal. Inténtalo de nuevo.';

const toCalls = (raw: any[]): BatchCall[] =>
  (raw || []).map((c: any) => ({ to: c.to, valueWei: BigInt(c.valueWei), data: c.data }));

const signBatch = async (
  calls: BatchCall[],
  intentId: string,
  wallet: { address: string; privKeyHex: string },
  delegateAddress: string,
) => {
  const [execNonce, delegated] = await Promise.all([
    delegateNonce(wallet.address),
    isDelegatedTo(wallet.address, delegateAddress),
  ]);
  const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);
  const digest = hashBatchIntent(calls, execNonce, deadline, intentId, wallet.address);
  const intentSignature = signIntentDigest(digest, wallet.privKeyHex);
  let authorization;
  if (!delegated) {
    const accountNonce = await bscGetNonce(wallet.address);
    authorization = signSetCodeAuthorization(delegateAddress, accountNonce, wallet.privKeyHex);
  }
  return { execNonce, deadline, intentSignature, authorization };
};

/** Sign and submit one order action whose calls the server already built. */
const signAndSubmit = async (
  orderId: string,
  action: MarketAction,
  calls: BatchCall[],
  intentId: string,
  extra: { disputeReason?: string } = {},
): Promise<{ txHash: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) throw new Error('sponsored_rail_unavailable');
  const wallet = await getActiveEvmWallet();

  const { ensureFaceCheck, FACE_STEP_UP_MESSAGE, FaceCheckError, isFaceStepUpRequired } =
    await import('./faceStepUp');
  let lastError = 'unknown';
  let faceRetried = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    const { execNonce, deadline, intentSignature, authorization } =
      await signBatch(calls, intentId, wallet, sponsored.delegateAddress);
    const res = await apolloClient.mutate({
      mutation: SUBMIT_ACTION,
      variables: {
        orderId,
        action,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
        disputeReason: extra.disputeReason || null,
      },
    });
    const sub = res.data?.submitMarketOrderAction;
    if (!sub?.success && isFaceStepUpRequired(sub?.error) && !faceRetried) {
      // The face window lapsed between prepare and submit: confirm again.
      faceRetried = true;
      if (!(await ensureFaceCheck('withdrawal'))) throw new FaceCheckError('cancelled', FACE_STEP_UP_MESSAGE);
      continue;
    }
    if (!sub?.success) {
      lastError = sub?.error || 'sponsor_rejected';
      // Nonce races are retryable with fresh reads; policy errors are not.
      if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
      throw new Error(lastError);
    }
    // The server's confirm task settles the order from the chain; a receipt
    // we don't get to see here is not a failure.
    return { txHash: sub.transactionHash };
  }
  throw new Error(lastError);
};

export interface CheckoutInput {
  /** The dollar amount the buyer saw; if the prepared order differs (FX moved
   *  or an older draft was reused), `confirmAmount` must approve the new one. */
  expectedAmountUsd?: string;
  productId: string;
  quantity: number;
  deliveryCountry: string;
  deliveryCity: string;
  deliveryAddress: string;
  deliveryPhone: string;
  deliveryNote?: string;
  outsideCityAck?: boolean;
}

/** Prepare the order (server signs the escrow authorization) and pay it. */
export const placeMarketOrder = async (
  input: CheckoutInput,
  confirmAmount: (amountUsd: string) => Promise<boolean>,
): Promise<{ orderId: string; txHash: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const { ensureFaceCheck, FACE_STEP_UP_MESSAGE, FaceCheckError, isFaceStepUpRequired } =
    await import('./faceStepUp');
  const { expectedAmountUsd, ...variables } = input;
  const prepare = async () => (await apolloClient.mutate({ mutation: PREPARE_ORDER, variables }))
    .data?.prepareMarketOrder;
  let prep = await prepare();
  if (!prep?.success && isFaceStepUpRequired(prep?.error)) {
    // A purchase is a payment: Confío Face, then once more (the draft is reused).
    if (!(await ensureFaceCheck('withdrawal'))) throw new FaceCheckError('cancelled', FACE_STEP_UP_MESSAGE);
    prep = await prepare();
  }
  if (!prep?.success) throw new Error(prep?.error || 'prepare_failed');
  const orderId = prep.order.id as string;
  // Never sign an amount the buyer did not see.
  if (expectedAmountUsd && Number(prep.order.amountUsd) !== Number(expectedAmountUsd)) {
    if (!(await confirmAmount(prep.order.amountUsd))) throw new Error('price_not_confirmed');
  }
  try {
    const { txHash } = await signAndSubmit(orderId, 'deposit', toCalls(prep.calls), prep.intentId);
    return { orderId, txHash };
  } catch (e: any) {
    if (e instanceof BscRevertedError) throw new Error('simulation_reverted');
    // A server answer with a code was rejected before any broadcast, so a
    // retry (which reuses this same order) is safe. Anything else — a dropped
    // connection mid-submit — may have paid: send the buyer to the order.
    if (e?.message && COMPRAR_ERRORS[e.message]) throw e;
    if (e?.message && /^[a-z_]+$/.test(e.message)) throw e;
    throw new MarketOutcomeUnknownError(orderId, e?.message);
  }
};

/** Run ship / confirm / dispute / refund / reclaim on an order. */
export const runMarketAction = async (
  orderId: string,
  action: Exclude<MarketAction, 'deposit'>,
  extra: { disputeReason?: string } = {},
): Promise<{ txHash: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const res = await apolloClient.mutate({ mutation: ACTION_CALLS, variables: { orderId, action } });
  const prep = res.data?.marketOrderActionCalls;
  if (!prep?.success) throw new Error(prep?.error || 'prepare_failed');
  return signAndSubmit(orderId, action, toCalls(prep.calls), prep.intentId, extra);
};

/** Upload one photo through a presigned POST; returns the pending key. */
export const uploadMarketPhoto = async (localUri: string, contentType: string): Promise<string> => {
  const { apolloClient } = await import('../apollo/client');
  const res = await apolloClient.mutate({ mutation: REQUEST_MARKET_PHOTO_UPLOAD, variables: { contentType } });
  const r = res.data?.requestMarketPhotoUpload;
  if (!r?.success || !r.upload) throw new Error(r?.error || 'upload_unavailable');
  const fields = typeof r.upload.fields === 'string' ? JSON.parse(r.upload.fields) : (r.upload.fields || {});
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v as string));
  form.append('file', { uri: localUri, type: contentType, name: 'upload' } as any);
  const upload = await fetch(r.upload.url, { method: 'POST', body: form });
  if (!upload.ok) throw new Error('upload_failed');
  return r.upload.key as string;
};

/** Spanish label for an order status, from the requester's side. */
export const orderStatusLabel = (status: string, role: 'buyer' | 'merchant'): string => {
  const buyer: Record<string, string> = {
    draft: 'Sin pagar', depositing: 'Procesando pago', funded: 'Pagado — esperando envío',
    shipped: 'En camino', disputed: 'En revisión', released: 'Completado',
    refunded: 'Reembolsado', cancelled: 'Cancelado',
  };
  const merchant: Record<string, string> = {
    ...buyer, funded: 'Nuevo pedido — prepáralo', shipped: 'Enviado',
    released: 'Pagado', depositing: 'Procesando pago',
  };
  return (role === 'merchant' ? merchant : buyer)[status] || status;
};
