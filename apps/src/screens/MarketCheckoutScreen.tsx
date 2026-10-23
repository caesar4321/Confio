import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  GET_CHECKOUT_QUOTE, GET_MARKETPLACE_PRODUCT, GET_MARKET_ORDER, MarketOutcomeUnknownError, comprarError,
  placeMarketOrder,
} from '../services/comprar';
import { formatLocalPrice, formatReference, formatUsd } from '../utils/comprarFormat';

/**
 * Checkout: the product is paid into the escrow in Confío dollars; delivery
 * is paid to the courier on arrival (Yango Envío), never through Confío.
 * Another city is allowed when the store ships there and the buyer accepts
 * the larger fee.
 */
export const MarketCheckoutScreen = () => {
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
  const [error, setError] = useState<string | null>(null);

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

  const city = (mode === 'same' ? store?.city : otherCity.trim()) ?? '';
  const country = store?.countryCode ?? '';
  const { data: quoteData, loading: quoting } = useQuery(GET_CHECKOUT_QUOTE, {
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

  const canPay = useMemo(() => (
    Boolean(quote) && address.trim().length >= 8 && phone.replace(/\D/g, '').length >= 7
      && (!outside || (store?.shipsOutsideCity && ack && city.length > 1)) && !paying
  ), [quote, address, phone, outside, store, ack, city, paying]);

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
      }));
      navigation.replace('MarketOrder', { orderId, justPaid: true });
    } catch (e: any) {
      if (e instanceof MarketOutcomeUnknownError) {
        // The payment may already be on its way: show the order, never retry.
        navigation.replace('MarketOrder', { orderId: e.orderId, justPaid: true });
        return;
      }
      setError(comprarError(e?.message));
    } finally {
      setPaying(false);
    }
  };

  if (!product) {
    return (
      <SafeAreaView style={styles.screen} edges={['top']}>
        <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <Header navigation={navigation} isHomeScreen={false} title="Confirmar compra" backgroundColor="#fff"
        showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.card}>
            <Text style={styles.productTitle}>{product.title}</Text>
            <Text style={styles.muted}>{store.name} · {store.city}</Text>
            <View style={styles.qtyRow}>
              <Text style={styles.label}>Cantidad</Text>
              {resuming ? (
                <Text style={styles.qty}>{quantity} (reservado)</Text>
              ) : (
                <View style={styles.stepper}>
                  <Pressable onPress={() => setQuantity((q) => Math.max(1, q - 1))} style={styles.stepButton}
                    accessibilityLabel="Menos"><Icon name="minus" size={16} color={colors.text.primary} /></Pressable>
                  <Text style={styles.qty}>{quantity}</Text>
                  <Pressable onPress={() => setQuantity((q) => Math.min(maxQty, q + 1))} style={styles.stepButton}
                    accessibilityLabel="Más"><Icon name="plus" size={16} color={colors.text.primary} /></Pressable>
                </View>
              )}
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Entrega</Text>
            <View style={styles.cityRow}>
              <Pressable style={[styles.cityOption, !outside && styles.cityOptionOn]} onPress={() => setMode('same')}>
                <Text style={[styles.cityText, !outside && styles.cityTextOn]}>En {store.city}</Text>
              </Pressable>
              <Pressable style={[styles.cityOption, outside && styles.cityOptionOn]}
                onPress={() => setMode('other')}>
                <Text style={[styles.cityText, outside && styles.cityTextOn]}>Otra ciudad</Text>
              </Pressable>
            </View>
            {outside && (
              <TextInput style={styles.input} placeholder="Ciudad de entrega" placeholderTextColor={colors.text.light}
                value={otherCity} onChangeText={setOtherCity} />
            )}
            <TextInput style={styles.input} placeholder="Dirección (calle, número, zona)" placeholderTextColor={colors.text.light}
              value={address} onChangeText={setAddress} />
            <TextInput style={styles.input} placeholder="Teléfono para el repartidor" placeholderTextColor={colors.text.light}
              keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
            <TextInput style={styles.input} placeholder="Referencia (opcional)" placeholderTextColor={colors.text.light}
              value={note} onChangeText={setNote} />
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
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Resumen</Text>
            {quoting && !quote ? <ActivityIndicator color={colors.primaryDark} /> : quote ? (
              <>
                <View style={styles.line}>
                  <Text style={styles.label}>Producto{quantity > 1 ? ` (${quantity} × ${formatUsd(quote.unitPriceUsd)})` : ''}</Text>
                  <Text style={styles.value}>{formatUsd(quote.amountUsd)}</Text>
                </View>
                {formatReference(quote.referenceLocal) ? (
                  <View style={styles.line}>
                    <Text style={styles.muted}>En moneda local, aprox.</Text>
                    <Text style={styles.muted}>{formatReference(quote.referenceLocal)}</Text>
                  </View>
                ) : null}
                <View style={styles.line}>
                  <Text style={styles.label}>Envío</Text>
                  <Text style={styles.value}>
                    {quote.deliveryEstimateLocal
                      ? `~${formatLocalPrice(quote.deliveryEstimateLocal, quote.deliveryCurrency || '')}`
                      : 'A coordinar'}
                  </Text>
                </View>
                <Text style={styles.muted}>
                  El envío se paga al repartidor{quote.deliveryPartner ? ` (${quote.deliveryPartner})` : ''} al recibir, con tu QR.
                </Text>
              </>
            ) : (
              <Text style={styles.warn}>No pudimos calcular el precio en dólares. Inténtalo en un momento.</Text>
            )}
          </View>

          <View style={styles.trust}>
            <Icon name="shield" size={16} color={colors.primaryDark} />
            <Text style={styles.trustText}>
              Tu pago queda guardado hasta que confirmes que recibiste el pedido. Si la tienda no lo envía, puedes recuperarlo.
            </Text>
          </View>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
        <View style={styles.footer}>
          <Pressable style={[styles.payButton, !canPay && styles.payDisabled]} disabled={!canPay} onPress={() => { void pay(); }}>
            {paying ? <ActivityIndicator color={colors.white} /> : (
              <Text style={styles.payText}>{quote ? `Pagar ${formatUsd(quote.amountUsd)}` : 'Pagar'}</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
};

export default MarketCheckoutScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  content: { padding: 16, gap: 12, paddingBottom: 120 },
  card: { backgroundColor: colors.white, borderRadius: 14, padding: 14, gap: 10 },
  productTitle: { fontSize: 16, fontWeight: '600', color: colors.textFlat },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  label: { fontSize: 14, color: colors.text.primary },
  value: { fontSize: 14, fontWeight: '600', color: colors.textFlat },
  muted: { fontSize: 13, color: colors.text.secondary },
  qtyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  stepButton: { width: 34, height: 34, borderRadius: 17, borderWidth: 1, borderColor: '#E5E7EB', alignItems: 'center', justifyContent: 'center' },
  qty: { fontSize: 16, fontWeight: '700', minWidth: 20, textAlign: 'center' },
  cityRow: { flexDirection: 'row', gap: 8 },
  cityOption: { flex: 1, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: '#E5E7EB', alignItems: 'center' },
  cityOptionOn: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  cityText: { fontSize: 14, color: colors.text.primary },
  cityTextOn: { fontWeight: '700', color: colors.onHeroField },
  input: { borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.text.primary },
  ackRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  ackText: { flex: 1, fontSize: 13, color: colors.text.primary },
  warn: { fontSize: 13, color: colors.warning.text },
  line: { flexDirection: 'row', justifyContent: 'space-between' },
  trust: { flexDirection: 'row', gap: 10, padding: 12, borderRadius: 12, backgroundColor: colors.primaryLight },
  trustText: { flex: 1, fontSize: 13, color: colors.onHeroField, lineHeight: 19 },
  error: { color: colors.error.text, fontSize: 14, textAlign: 'center' },
  footer: { padding: 16, paddingBottom: 28, backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: '#F0F0F0' },
  payButton: { backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 15, alignItems: 'center' },
  payDisabled: { backgroundColor: '#D1D5DB' },
  payText: { color: colors.white, fontSize: 16, fontWeight: '700' },
});
