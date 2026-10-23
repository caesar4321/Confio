import React, { useEffect, useMemo, useState } from 'react';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import {
  CheckoutStage, DeliveryAddress, GET_CHECKOUT_QUOTE, GET_DELIVERY_ADDRESSES, GET_MARKETPLACE_PRODUCT, GET_MARKET_ORDER,
  MarketOutcomeUnknownError, SAVE_DELIVERY_ADDRESS, comprarError, placeMarketOrder,
} from '../services/comprar';
import { AddressBookSheet } from '../components/comprar/AddressBookSheet';
import { ComprarFrame, KitButton, KitCard, KitFooter, KitRow, ProductThumb, TrustNote, kitText } from '../components/comprar/kit';
import { formatReference, formatUsd } from '../utils/comprarFormat';

/**
 * Checkout: the product is paid into the escrow in Confío dollars; delivery
 * is paid to the courier on arrival (Yango Envío), never through Confío.
 * Another city is allowed when the store ships there and the buyer accepts
 * the larger fee.
 */
export const MarketCheckoutScreen = () => {
  useNumberLocale(); // amounts follow the user's number format, live
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const productId = route.params?.productId as string;
  const { data: productData } = useQuery(GET_MARKETPLACE_PRODUCT, { variables: { id: productId } });
  const product = productData?.marketplaceProduct;
  const store = product?.store;

  const [quantity, setQuantity] = useState(1);
  const [mode, setMode] = useState<'same' | 'other'>('same');
  const [otherCity, setOtherCity] = useState('');
  const [address, setAddress] = useState('');
  const [phone, setPhone] = useState('');
  const [note, setNote] = useState('');
  const [ack, setAck] = useState(false);
  const [paying, setPaying] = useState(false);
  // Blocks the screen while the order is prepared and paid; steps aside for
  // Confío Face and the changed-price question, which need the buyer.
  const [stage, setStage] = useState<CheckoutStage | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Address book: a picked entry fills the delivery fields; null = typed for
  // this order (offered to the book after paying).
  const [picked, setPicked] = useState<DeliveryAddress | null>(null);
  const [bookOpen, setBookOpen] = useState(false);
  const [saveToBook, setSaveToBook] = useState(true);
  const [autoPicked, setAutoPicked] = useState(false);
  const { data: bookData } = useQuery(GET_DELIVERY_ADDRESSES, { fetchPolicy: 'cache-and-network' });
  const [saveAddress] = useMutation(SAVE_DELIVERY_ADDRESS);

  // Resuming an unpaid draft: same quantity and delivery details, so the
  // server reuses its authorization and the units it already holds.
  const resumeOrderId = route.params?.resumeOrderId as string | undefined;
  const { data: resumeData } = useQuery(GET_MARKET_ORDER, {
    variables: { id: resumeOrderId }, skip: !resumeOrderId,
  });
  const resume = resumeData?.marketOrder;
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (!resume || seeded || resume.status !== 'draft') return;
    setQuantity(resume.quantity);
    setAddress(resume.deliveryAddress || '');
    setPhone(resume.deliveryPhone || '');
    setNote(resume.deliveryNote || '');
    if (resume.deliveryOutsideCity) {
      setMode('other');
      setOtherCity(resume.deliveryCity || '');
      setAck(true);
    }
    setSeeded(true);
  }, [resume, seeded]);

  const sameCity = (a: string, b?: string) =>
    a.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase()
      === (b || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
  const pickAddress = (a: DeliveryAddress | null) => {
    setBookOpen(false);
    setPicked(a);
    if (!a) return; // typing one for this order: keep what is in the fields
    setAddress(a.address);
    setPhone(a.phone);
    setNote(a.note || '');
    if (sameCity(a.city, store?.city)) {
      setMode('same');
    } else {
      setMode('other');
      setOtherCity(a.city);
    }
    setAck(false);
  };
  // Preselect the default (else most recent, else the Recarga address) once,
  // only in the store's country, and never over a resumed draft's address.
  useEffect(() => {
    if (autoPicked || resumeOrderId || !store || !bookData?.myDeliveryAddresses) return;
    setAutoPicked(true);
    if (address || phone) return;
    const first = (bookData.myDeliveryAddresses as DeliveryAddress[])
      .find((a) => (a.countryCode || '').toUpperCase() === (store.countryCode || '').toUpperCase());
    if (first) pickAddress(first);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPicked, resumeOrderId, store, bookData]);

  const city = (mode === 'same' ? store?.city : otherCity.trim()) ?? '';
  const country = store?.countryCode ?? '';
  const { data: quoteData, loading: quoting, refetch: requote } = useQuery(GET_CHECKOUT_QUOTE, {
    variables: { productId, quantity, deliveryCountry: country, deliveryCity: city },
    skip: !store || !city,
    fetchPolicy: 'network-only',
  });
  const quote = quoteData?.marketCheckoutQuote;
  // From the buyer's choice, not the quote: while the city is still being
  // typed there is no quote, and that must not read as "same city".
  const outside = mode === 'other';
  // A buyer re-opening their own reserved draft may see stock 0; the server
  // enforces the real limit at reservation.
  // A resumed draft keeps the quantity it reserved (that is what makes it
  // reusable); a new quantity would need free stock of its own.
  const resuming = resume?.status === 'draft';
  const maxQty = Math.min(Math.max(product?.stock ?? 1, 1), 20);

  // What still stands between the buyer and Pagar, said on the button's
  // doorstep: the rules match the server's (checkout.prepare_order).
  const blocker = useMemo((): string | null => {
    if (outside && !store?.shipsOutsideCity) return `Esta tienda solo entrega en ${store?.city ?? 'su ciudad'}.`;
    if (outside && city.length < 2) return 'Escribe la ciudad de entrega.';
    if (!quote) return quoting ? 'Calculando el total…' : 'No pudimos calcular el total.';
    if (address.trim().length < 8) return 'Escribe la dirección completa (calle, número y zona).';
    if (phone.replace(/\D/g, '').length < 7) return 'Escribe un teléfono para el repartidor.';
    if (outside && !ack) return 'Confirma que entiendes el costo del envío a otra ciudad.';
    return null;
  }, [quote, quoting, address, phone, outside, store, ack, city]);
  const canPay = !blocker && !paying;

  // After a payment (or one whose outcome is unknown: the order opens either
  // way), remember the address: a book entry moves up as recently used, the
  // Recarga address or a typed one (if the switch is on) joins the book.
  // Fire and forget: the book never holds up or fails a purchase.
  const rememberAddress = () => {
    if (!picked && !saveToBook) return;
    void saveAddress({ variables: {
      label: picked?.source === 'saved' ? '' : (picked?.label || ''),
      countryCode: country, city, address: address.trim(), phone: phone.trim(), note: note.trim(), markUsed: true,
    } }).catch(() => {});
  };

  const pay = async () => {
    setError(null);
    setPaying(true);
    try {
      const { orderId } = await placeMarketOrder({
        expectedAmountUsd: quote?.amountUsd,
        productId, quantity, deliveryCountry: country, deliveryCity: city,
        deliveryAddress: address.trim(), deliveryPhone: phone.trim(), deliveryNote: note.trim(),
        outsideCityAck: outside ? ack : false,
      }, (amountUsd) => new Promise((resolve) => {
        Alert.alert('El precio cambió', `El total ahora es ${formatUsd(amountUsd)}. ¿Pagar este monto?`, [
          { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
          { text: 'Pagar', onPress: () => resolve(true) },
        ]);
      }), setStage);
      rememberAddress();
      navigation.replace('MarketOrder', { orderId, justPaid: true });
    } catch (e: any) {
      if (e instanceof MarketOutcomeUnknownError) {
        // The payment may already be on its way: show the order, never retry.
        rememberAddress();
        navigation.replace('MarketOrder', { orderId: e.orderId, justPaid: true });
        return;
      }
      setError(comprarError(e?.message));
    } finally {
      setPaying(false);
      setStage(null);
    }
  };

  if (!product) {
    return (
      <ComprarFrame title="Confirmar compra">
        <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
      </ComprarFrame>
    );
  }

  const blocking = paying && (stage === 'preparing' || stage === 'paying')
    ? (stage === 'paying' && quote ? `Pagando ${formatUsd(quote.amountUsd)}…` : 'Preparando tu compra…')
    : null;
  return (
    <ComprarFrame title="Confirmar compra" blocking={blocking}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <KitCard>
            <View style={styles.productRow}>
              <ProductThumb uri={product.photoUrls?.[0]} size={64} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.productTitle} numberOfLines={2}>{product.title}</Text>
                <Text style={kitText.muted} numberOfLines={1}>{store.name} · {store.city}</Text>
                <Text style={styles.unitPrice}>{formatUsd(quote?.unitPriceUsd ?? product.priceUsd)}</Text>
              </View>
            </View>
            <View style={styles.divider} />
            <View style={styles.qtyRow}>
              <Text style={styles.label}>Cantidad</Text>
              {resuming ? (
                <Text style={styles.qty}>{quantity} (reservado)</Text>
              ) : (
                <View style={styles.stepper}>
                  <Pressable onPress={() => setQuantity((q) => Math.max(1, q - 1))} style={styles.stepButton}
                    disabled={quantity <= 1} accessibilityLabel="Menos">
                    <Icon name="minus" size={16} color={quantity <= 1 ? colors.text.light : colors.text.primary} />
                  </Pressable>
                  <Text style={styles.qty}>{quantity}</Text>
                  <Pressable onPress={() => setQuantity((q) => Math.min(maxQty, q + 1))} style={styles.stepButton}
                    disabled={quantity >= maxQty} accessibilityLabel="Más">
                    <Icon name="plus" size={16} color={quantity >= maxQty ? colors.text.light : colors.text.primary} />
                  </Pressable>
                </View>
              )}
            </View>
          </KitCard>

          <KitCard icon="truck" title="Entrega"
            right={picked || bookData?.myDeliveryAddresses?.length ? (
              <Pressable onPress={() => setBookOpen(true)} hitSlop={8} testID="checkout-change-address">
                <Text style={kitText.link}>{picked ? 'Cambiar' : 'Mis direcciones'}</Text>
              </Pressable>
            ) : null}>
            {picked ? (
              <Pressable style={styles.pickedCard} onPress={() => setBookOpen(true)} testID="checkout-picked-address">
                <Icon name={picked.source === 'recarga' ? 'credit-card' : 'map-pin'} size={18} color={colors.primaryDeep} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.pickedLabel}>{picked.label || 'Dirección'}</Text>
                  <Text style={kitText.body}>{picked.address}</Text>
                  <Text style={kitText.muted}>{picked.city} · {picked.phone}{picked.note ? ` · ${picked.note}` : ''}</Text>
                </View>
              </Pressable>
            ) : (<>
            <View style={styles.cityRow}>
              {([['same', `En ${store.city}`, 'map-pin'], ['other', 'Otra ciudad', 'navigation']] as const).map(([m, label, icon]) => {
                const on = mode === m;
                return (
                  <Pressable key={m} style={[styles.cityOption, on && styles.cityOptionOn]} onPress={() => setMode(m)}
                    accessibilityRole="radio" accessibilityState={{ checked: on }}>
                    <Icon name={icon} size={15} color={on ? colors.primaryDeep : colors.text.secondary} />
                    <Text style={[styles.cityText, on && styles.cityTextOn]} numberOfLines={1}>{label}</Text>
                  </Pressable>
                );
              })}
            </View>
            {outside && (
              <Field icon="map" placeholder="Ciudad de entrega" value={otherCity} onChangeText={setOtherCity} />
            )}
            <Field icon="home" placeholder="Dirección (calle, número, zona)" value={address} onChangeText={setAddress} />
            <Field icon="phone" placeholder="Teléfono para el repartidor" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
            <Field icon="message-square" placeholder="Referencia (opcional)" value={note} onChangeText={setNote} />
            <View style={styles.ackRow}>
              <Switch value={saveToBook} onValueChange={setSaveToBook} testID="checkout-save-address" />
              <Text style={styles.ackText}>Guardar en mis direcciones</Text>
            </View>
            </>)}
            {outside && !store.shipsOutsideCity ? (
              <Text style={styles.warn}>Esta tienda solo entrega en {store.city}.</Text>
            ) : outside ? (
              <View style={styles.ackRow}>
                <Switch value={ack} onValueChange={setAck} />
                <Text style={styles.ackText}>
                  Entiendo que el envío a otra ciudad lo coordina la tienda y cuesta más que un envío en {store.city}.
                </Text>
              </View>
            ) : null}
          </KitCard>

          <KitCard icon="file-text" title="Resumen">
            {quoting && !quote ? <ActivityIndicator color={colors.primaryDark} /> : quote ? (
              <>
                <KitRow label={quantity > 1 ? `Producto (${quantity} × ${formatUsd(quote.unitPriceUsd)})` : 'Producto'}
                  value={formatUsd(quote.productUsd ?? quote.amountUsd)} />
                {/* Same-city delivery is the store's price, inside the total;
                    another city is coordinated with the store. */}
                <KitRow label={`Envío en ${city}`} muted value={quote.outsideCity
                  ? 'A coordinar con la tienda'
                  : Number(quote.deliveryUsd ?? 0) > 0 ? formatUsd(quote.deliveryUsd) : 'Gratis'} />
                <View style={styles.divider} />
                <KitRow label="Total" strong value={formatUsd(quote.amountUsd)} />
                {formatReference(quote.referenceLocal) ? (
                  <Text style={[kitText.muted, styles.right]}>{formatReference(quote.referenceLocal)} en moneda local</Text>
                ) : null}
                <Text style={kitText.muted}>
                  {quote.outsideCity
                    ? 'La tienda coordina contigo el envío a otra ciudad y su costo.'
                    : 'La tienda envía tu pedido a tu dirección. El repartidor te escribirá o llamará al teléfono que pusiste.'}
                </Text>
              </>
            ) : (
              <Pressable onPress={() => { void requote().catch(() => {}); }} testID="checkout-requote" style={styles.retry}>
                <Icon name="refresh-cw" size={15} color={colors.warning.text} />
                <Text style={styles.warn}>No pudimos calcular el total. Toca para reintentar.</Text>
              </Pressable>
            )}
          </KitCard>

          <AddressBookSheet visible={bookOpen} selectedId={picked?.id ?? null}
            countryCode={store.countryCode} city={store.city}
            onClose={() => setBookOpen(false)} onSelect={pickAddress} />
          <TrustNote>
            Tu pago queda guardado hasta que confirmes que recibiste el pedido. Si la tienda no lo envía, puedes recuperarlo.
          </TrustNote>
          {error ? <Text style={kitText.error}>{error}</Text> : null}
        </ScrollView>
        <KitFooter>
          {blocker && !paying ? <Text style={styles.blocker} testID="checkout-blocker">{blocker}</Text> : null}
          <KitButton testID="checkout-pay" disabled={!canPay} loading={paying} icon="lock"
            label={quote ? `Pagar ${formatUsd(quote.amountUsd)}` : 'Pagar'} onPress={() => { void pay(); }} />
        </KitFooter>
      </KeyboardAvoidingView>
    </ComprarFrame>
  );
};

const Field = ({ icon, ...props }: { icon: string } & React.ComponentProps<typeof TextInput>) => (
  <View style={styles.field}>
    <Icon name={icon} size={16} color={colors.text.light} />
    <TextInput style={styles.fieldInput} placeholderTextColor={colors.text.light} {...props} />
  </View>
);

export default MarketCheckoutScreen;

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 32 },
  productRow: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  productTitle: { fontSize: 16, fontWeight: '600', color: colors.textFlat },
  unitPrice: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 2 },
  divider: { height: 1, backgroundColor: colors.borderLight },
  label: { fontSize: 14, color: colors.text.primary },
  qtyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: colors.neutral, borderRadius: 999, padding: 4 },
  stepButton: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  qty: { fontSize: 16, fontWeight: '700', minWidth: 20, textAlign: 'center', color: colors.textFlat },
  cityRow: { flexDirection: 'row', gap: 8 },
  cityOption: { flex: 1, flexDirection: 'row', gap: 6, paddingVertical: 11, borderRadius: 12, borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' },
  cityOptionOn: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  cityText: { fontSize: 14, color: colors.text.primary },
  cityTextOn: { fontWeight: '700', color: colors.primaryDeep },
  field: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12, backgroundColor: colors.white },
  fieldInput: { flex: 1, paddingVertical: 12, fontSize: 15, color: colors.text.primary },
  ackRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pickedCard: { flexDirection: 'row', gap: 12, padding: 12, borderRadius: 12, backgroundColor: colors.neutral, alignItems: 'flex-start' },
  pickedLabel: { fontSize: 14, fontWeight: '700', color: colors.textFlat },
  ackText: { flex: 1, fontSize: 13, color: colors.text.primary, lineHeight: 18 },
  warn: { fontSize: 13, color: colors.warning.text, flexShrink: 1 },
  retry: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  right: { textAlign: 'right', marginTop: -6 },
  blocker: { fontSize: 13, color: colors.text.secondary, textAlign: 'center' },
});
