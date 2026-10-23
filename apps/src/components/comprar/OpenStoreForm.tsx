import React, { useRef, useState } from 'react';
import { useNumberLocale } from '../../contexts/NumberLocaleProvider';
import {
  ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView, StatusBar,
  StyleSheet, Switch, TextInput as RNTextInput, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text, TextInput } from '../common/AppText';
import { BrandFieldBackground } from '../common/BrandFieldBackground';
import { colors } from '../../config/theme';
import { formatFeeBps, formatLocalPrice } from '../../utils/comprarFormat';
import { normalizeAmountInput } from '../../utils/numberLocale';

const NAME_MAX = 80;
const DESCRIPTION_MAX = 1000;

type Props = {
  feeBps?: number | null;
  city: string;
  accountLabel: string;
  submitting: boolean;
  error: string | null;
  onBack: () => void;
  onPickCity: () => void;
  onSubmit: (values: {
    name: string; description: string; shipsOutsideCity: boolean; deliveryPriceUsd: string;
    outsideDeliveryPriceUsd: string | null;
  }) => void;
  /** The city's suggested delivery price (US$), pre-filled until edited. */
  suggestedDeliveryUsd?: string | null;
  /** Display-only "≈ Bs" for the delivery price. */
  localRate?: { currency: string; localPerUsd: string } | null;
};

/**
 * "Abrir mi tienda": a brand hero that sells the idea, then one card with
 * the four things a store needs. Built for the keyboard: the form scrolls,
 * tapping outside or dragging dismisses it, "Siguiente" walks the fields,
 * and the button stays pinned above the keyboard so it can always be reached.
 */
export const OpenStoreForm = ({
  feeBps, city, accountLabel, submitting, error, onBack, onPickCity, onSubmit, suggestedDeliveryUsd, localRate,
}: Props) => {
  const { separators, parseAmount, sanitizeAmount, toAmountInput } = useNumberLocale();
  const insets = useSafeAreaInsets();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [shipsOutside, setShipsOutside] = useState(false);
  // The delivery price follows the city's suggestion until the seller edits it.
  const [delivery, setDelivery] = useState('');
  const [deliveryEdited, setDeliveryEdited] = useState(false);
  React.useEffect(() => {
    if (!deliveryEdited && suggestedDeliveryUsd) setDelivery(toAmountInput(Number(suggestedDeliveryUsd), 2));
  }, [suggestedDeliveryUsd, deliveryEdited, toAmountInput]);
  const deliveryValue = parseAmount(delivery);
  const deliveryOk = delivery.trim() !== '' && deliveryValue >= 0 && deliveryValue <= 100;
  // Other cities are offered only with their own flat price.
  const [outsideDelivery, setOutsideDelivery] = useState('');
  const outsideValue = parseAmount(outsideDelivery);
  const outsideOk = !shipsOutside || (outsideDelivery.trim() !== '' && outsideValue >= 0 && outsideValue <= 100);
  const descriptionRef = useRef<RNTextInput>(null);
  const fee = formatFeeBps(feeBps);
  const valid = name.trim().length >= 2 && Boolean(city) && deliveryOk && outsideOk && !submitting;

  const submit = () => {
    Keyboard.dismiss();
    if (valid) {
      onSubmit({
        name: name.trim(), description: description.trim(), shipsOutsideCity: shipsOutside,
        deliveryPriceUsd: normalizeAmountInput(delivery) ?? '',
        outsideDeliveryPriceUsd: shipsOutside ? (normalizeAmountInput(outsideDelivery) ?? '') : null,
      });
    }
  };

  const benefits = [
    { icon: 'percent', title: 'Sin mensualidades', body: fee ? `Pagas ${fee} solo cuando vendes.` : 'Pagas solo cuando vendes.' },
    { icon: 'user-check', title: 'Compradores verificados', body: 'Todos confirman su identidad antes de comprar.' },
    { icon: 'shield', title: 'Pago protegido', body: 'El pago queda guardado y te llega al entregar.' },
    { icon: 'dollar-sign', title: 'Cobras en dólares', body: 'Directo a tu cuenta Confío.' },
  ];

  return (
    <View style={styles.screen}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      {/* A fixed green strip under the status bar: light text stays readable
          after the hero scrolls away (iOS ignores backgroundColor above). */}
      <View pointerEvents="none" style={[styles.statusStrip, { height: insets.top }]} />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
          contentContainerStyle={{ paddingBottom: 24 }}
          showsVerticalScrollIndicator={false}
        >
          <Pressable onPress={Keyboard.dismiss} accessible={false}>
            <View style={styles.hero}>
              <BrandFieldBackground id="openStoreField" ringCx="100%" ringCy="18%" ringR={96} ringWidth={22} />
              <View style={[styles.heroInner, { paddingTop: insets.top + 8 }]}>
                <Pressable onPress={onBack} style={styles.back} hitSlop={10} accessibilityRole="button"
                  accessibilityLabel="Volver">
                  <Icon name="arrow-left" size={22} color={colors.white} />
                </Pressable>
                <View style={styles.badge}>
                  <Icon name="shopping-bag" size={14} color={colors.onHeroField} />
                  <Text style={styles.badgeText}>Comprar</Text>
                </View>
                <Text style={styles.heroHeadline}>Abre tu tienda en Confío</Text>
                <Text style={styles.heroSub}>Vende a compradores verificados de tu ciudad, sin local y sin mensualidades.</Text>
              </View>
            </View>

            <View style={styles.benefits}>
              {benefits.map((b) => (
                <View key={b.title} style={styles.benefit}>
                  <View style={styles.benefitIcon}><Icon name={b.icon} size={16} color={colors.primaryDark} /></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.benefitTitle}>{b.title}</Text>
                    <Text style={styles.benefitBody}>{b.body}</Text>
                  </View>
                </View>
              ))}
            </View>
          </Pressable>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Tu tienda</Text>

            <View style={styles.field}>
              <View style={styles.labelRow}>
                <Text style={styles.label}>Nombre</Text>
                <Text style={styles.counter}>{name.length}/{NAME_MAX}</Text>
              </View>
              <TextInput
                style={styles.input}
                placeholder="Ej.: Tejidos Doña Ana"
                placeholderTextColor={colors.text.light}
                value={name}
                onChangeText={setName}
                maxLength={NAME_MAX}
                autoCapitalize="words"
                returnKeyType="next"
                blurOnSubmit={false}
                onSubmitEditing={() => descriptionRef.current?.focus()}
              />
            </View>

            <View style={styles.field}>
              <View style={styles.labelRow}>
                <Text style={styles.label}>¿Qué vendes? <Text style={styles.optional}>(opcional)</Text></Text>
                <Text style={styles.counter}>{description.length}/{DESCRIPTION_MAX}</Text>
              </View>
              <TextInput
                ref={descriptionRef}
                style={[styles.input, styles.multiline]}
                placeholder="Ej.: chompas y chalinas de alpaca hechas a mano en El Alto"
                placeholderTextColor={colors.text.light}
                value={description}
                onChangeText={setDescription}
                maxLength={DESCRIPTION_MAX}
                multiline
                textAlignVertical="top"
                returnKeyType="done"
                blurOnSubmit
                onSubmitEditing={Keyboard.dismiss}
              />
            </View>

            <Pressable style={styles.row} onPress={() => { Keyboard.dismiss(); onPickCity(); }} accessibilityRole="button"
              accessibilityLabel="Elegir ciudad">
              <View style={styles.rowIcon}><Icon name="map-pin" size={16} color={colors.primaryDark} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Ciudad</Text>
                <Text style={[styles.rowValue, !city && styles.rowPlaceholder]}>{city || 'Elige dónde vendes'}</Text>
              </View>
              <Icon name="chevron-right" size={18} color={colors.text.light} />
            </Pressable>

            <View style={styles.row}>
              <View style={styles.rowIcon}><Icon name="send" size={16} color={colors.primaryDark} /></View>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.label}>Envío en {city || 'tu ciudad'}</Text>
                <View style={styles.deliveryRow}>
                  <Text style={styles.deliveryPrefix}>US$</Text>
                  <TextInput testID="open-store-delivery" style={[styles.input, styles.deliveryInput]}
                    keyboardType="decimal-pad" placeholder={`0${separators.decimal}00`} placeholderTextColor={colors.text.light}
                    value={delivery} onChangeText={(t) => { setDeliveryEdited(true); setDelivery((prev) => sanitizeAmount(t, 2, undefined, prev)); }} />
                  {localRate && deliveryOk && deliveryValue > 0 ? (
                    <Text style={styles.hint}>≈ {formatLocalPrice(deliveryValue * Number(localRate.localPerUsd), localRate.currency)}</Text>
                  ) : null}
                </View>
                <Text style={styles.hint}>
                  Lo paga el comprador junto con el producto. Tú envías el pedido (con Yango Envíos o tu propio repartidor) y te llega con el pago. 0 = envío gratis.
                </Text>
              </View>
            </View>

            <View style={styles.row}>
              <View style={styles.rowIcon}><Icon name="truck" size={16} color={colors.primaryDark} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Envíos a otras ciudades</Text>
                <Text style={styles.hint}>
                  {shipsOutside
                    ? 'Un precio fijo para cualquier otra ciudad del país (encomienda o courier), incluido en el pago.'
                    : city ? `Solo entregas en ${city} y alrededores.` : 'Solo entregas en tu ciudad.'}
                </Text>
                {shipsOutside ? (
                  <View style={styles.deliveryRow}>
                    <Text style={styles.deliveryPrefix}>US$</Text>
                    <TextInput testID="open-store-outside-delivery" style={[styles.input, styles.deliveryInput]}
                      keyboardType="decimal-pad" placeholder={`0${separators.decimal}00`} placeholderTextColor={colors.text.light}
                      value={outsideDelivery} onChangeText={(t) => setOutsideDelivery((prev) => sanitizeAmount(t, 2, undefined, prev))} />
                    {localRate && outsideOk && outsideValue > 0 ? (
                      <Text style={styles.hint}>≈ {formatLocalPrice(outsideValue * Number(localRate.localPerUsd), localRate.currency)}</Text>
                    ) : null}
                  </View>
                ) : null}
              </View>
              <Switch value={shipsOutside} onValueChange={(v) => { Keyboard.dismiss(); setShipsOutside(v); }} />
            </View>

            <View style={styles.account}>
              <Icon name="briefcase" size={14} color={colors.text.secondary} />
              <Text style={styles.accountText}>Se abrirá en {accountLabel}</Text>
            </View>
          </View>
        </ScrollView>

        {/* The app shell already reserves the bottom safe area. */}
        <View style={[styles.footer, { paddingBottom: 12 }]}>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable testID="open-store-submit" style={[styles.primary, !valid && styles.disabled]} disabled={!valid} onPress={submit}
            accessibilityRole="button" accessibilityState={{ disabled: !valid }}>
            {submitting ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryText}>Abrir tienda</Text>}
          </Pressable>
          <Text style={styles.footnote}>Después agregas tus productos con fotos. Cada publicación se revisa antes de mostrarse.</Text>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
};

const styles = StyleSheet.create({
  deliveryRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  deliveryPrefix: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  deliveryInput: { width: 96, paddingVertical: 8 },
  screen: { flex: 1, backgroundColor: colors.neutral },
  statusStrip: { position: 'absolute', top: 0, left: 0, right: 0, backgroundColor: colors.heroField, zIndex: 10 },
  hero: { backgroundColor: colors.heroField, overflow: 'hidden' },
  heroInner: { paddingHorizontal: 20, paddingBottom: 28 },
  back: { width: 36, height: 36, justifyContent: 'center', marginBottom: 8 },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: 'rgba(255,255,255,0.85)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  badgeText: { fontSize: 12, fontWeight: '700', color: colors.onHeroField },
  heroHeadline: { fontSize: 26, fontWeight: '800', color: colors.white, marginTop: 12 },
  heroSub: { fontSize: 15, lineHeight: 21, color: colors.white, opacity: 0.92, marginTop: 6 },
  benefits: { backgroundColor: colors.white, marginHorizontal: 16, marginTop: -14, borderRadius: 20, padding: 16, gap: 14, borderWidth: 1, borderColor: '#EEF2F0' },
  benefit: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  benefitIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  benefitTitle: { fontSize: 14, fontWeight: '700', color: colors.textFlat },
  benefitBody: { fontSize: 13, color: colors.text.secondary, marginTop: 1, lineHeight: 18 },
  card: { backgroundColor: colors.white, marginHorizontal: 16, marginTop: 14, borderRadius: 20, padding: 16, gap: 16, borderWidth: 1, borderColor: '#EEF2F0' },
  cardTitle: { fontSize: 17, fontWeight: '800', color: colors.textFlat },
  field: { gap: 6 },
  labelRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  label: { fontSize: 13, fontWeight: '700', color: colors.textFlat },
  optional: { fontWeight: '400', color: colors.text.secondary },
  counter: { fontSize: 12, color: colors.text.light },
  input: { backgroundColor: colors.neutral, borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: colors.text.primary },
  multiline: { minHeight: 96 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  rowIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  rowValue: { fontSize: 15, color: colors.text.primary, marginTop: 2 },
  rowPlaceholder: { color: colors.text.light },
  hint: { fontSize: 13, color: colors.text.secondary, marginTop: 2, lineHeight: 18 },
  account: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingTop: 4, borderTopWidth: 1, borderTopColor: '#F1F3F2' },
  accountText: { fontSize: 12, color: colors.text.secondary, marginTop: 10 },
  footer: { backgroundColor: colors.white, paddingHorizontal: 16, paddingTop: 12, borderTopWidth: 1, borderTopColor: '#EEF2F0', gap: 8 },
  primary: { backgroundColor: colors.primaryDark, borderRadius: 16, paddingVertical: 16, alignItems: 'center' },
  disabled: { backgroundColor: '#D1D5DB' },
  primaryText: { color: colors.white, fontSize: 16, fontWeight: '800' },
  footnote: { fontSize: 12, color: colors.text.secondary, textAlign: 'center' },
  error: { color: colors.error.text, fontSize: 14, textAlign: 'center' },
});
