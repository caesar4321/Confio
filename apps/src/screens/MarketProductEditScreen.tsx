import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import {
  GET_MARKETPLACE_AGE_RULES, GET_MY_MARKET_STORE, GET_REFERENCE_RATE, SAVE_MARKET_PRODUCT, comprarError,
  type MarketplaceAgeRules, uploadMarketPhoto,
} from '../services/comprar';
import { formatFeeBps, formatLocalPrice, formatUsd } from '../utils/comprarFormat';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import { normalizeAmountInput } from '../utils/numberLocale';
import { CategoryPicker } from '../components/comprar/CategoryPicker';
import { pickFromLibrary } from '../services/systemPicker';
import { AdultsOnlyNote, ComprarFrame, KitButton, KitCard, KitFooter } from '../components/comprar/kit';

const MAX_PHOTOS = 4;
// Camera originals at full size can pass the 5 MB upload cap; this keeps them
// well under it and still sharp on a phone screen.
const PHOTO_MAX_SIDE = 1600;

type Photo = { uri: string; key?: string; uploading?: boolean };

/**
 * Create or edit a listing. Every save goes through moderation again
 * ("En revisión"); new photos replace the old ones once approved.
 */
export const MarketProductEditScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const productId = route.params?.productId as string | undefined;
  const { data } = useQuery(GET_MY_MARKET_STORE);
  const { data: ageData } = useQuery<{ marketplaceAgeRules: MarketplaceAgeRules | null }>(GET_MARKETPLACE_AGE_RULES);
  const ageRules = ageData?.marketplaceAgeRules ?? null;
  const existing = (data?.myMarketStoreProducts || []).find((p: any) => String(p.id) === productId);
  // Display-only "≈ Bs" while typing; the price itself is in dollars.
  const storeCountry = data?.myMarketStore?.countryCode;
  const { data: rateData } = useQuery(GET_REFERENCE_RATE, {
    variables: { countryCode: storeCountry || '' }, skip: !storeCountry,
  });
  const rate = rateData?.marketplaceReferenceRate;
  const categories = data?.marketplaceCategories || [];
  const [save, { loading: saving }] = useMutation(SAVE_MARKET_PRODUCT);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  // Typed and shown with the user's decimal mark (1.234,56 vs 1,234.56); sent
  // to the server as the canonical "1234.56".
  const { separators, parseAmount, sanitizeAmount, toAmountInput } = useNumberLocale();
  const [price, setPrice] = useState('');
  const [stock, setStock] = useState('1');
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [seeded, setSeeded] = useState(false);
  // The stock the form loaded: the server applies the seller's change as a
  // delta from it, so units reserved meanwhile stay reserved.
  const [loadedStock, setLoadedStock] = useState<number | null>(null);
  const [loadedRevision, setLoadedRevision] = useState<number | null>(null);

  useEffect(() => {
    if (existing && !seeded) {
      setTitle(existing.title);
      setDescription(existing.description || '');
      setCategory(existing.category);
      setPrice(toAmountInput(Number(existing.priceUsd), 2));
      setStock(String(existing.stock));
      setLoadedStock(existing.stock);
      setLoadedRevision(existing.stockRevision ?? 0);
      setSeeded(true);
    }
  }, [existing, seeded]);

  const addPhoto = async () => {
    setPhotoError(null);
    // Through the picker guard: a slow pick must not trip the resume lock,
    // whose unlock lands on Home and throws away this form mid-upload.
    const res = await pickFromLibrary({
      mediaType: 'photo', selectionLimit: MAX_PHOTOS - photos.length, quality: 0.8,
      maxWidth: PHOTO_MAX_SIDE, maxHeight: PHOTO_MAX_SIDE,
    });
    if (res.errorCode) {
      setPhotoError(res.errorCode === 'permission'
        ? 'Permite el acceso a tus fotos en Ajustes para agregar fotos.'
        : 'No pudimos abrir tus fotos. Inténtalo de nuevo.');
      return;
    }
    for (const asset of res.assets || []) {
      if (!asset.uri) continue;
      const type = asset.type || 'image/jpeg';
      const placeholder: Photo = { uri: asset.uri, uploading: true };
      setPhotos((prev) => [...prev, placeholder]);
      try {
        const key = await uploadMarketPhoto(asset.uri, type);
        setPhotos((prev) => prev.map((p) => (p === placeholder ? { uri: asset.uri as string, key } : p)));
      } catch (e: any) {
        setPhotos((prev) => prev.filter((p) => p !== placeholder));
        setPhotoError(comprarError(e?.message));
      }
    }
  };

  const uploading = photos.some((p) => p.uploading);
  const newKeys = photos.filter((p) => p.key).map((p) => p.key as string);
  const priceValue = parseAmount(price);
  const valid = title.trim().length >= 3 && category && priceValue >= 0.5 && Number.isInteger(Number(stock))
    && (productId ? true : newKeys.length > 0);

  const submit = async () => {
    setError(null);
    let r: any;
    try {
      const res = await save({ variables: {
        productId: productId || null, title: title.trim(), description: description.trim(), category,
        priceUsd: normalizeAmountInput(price) ?? '', stock: Number(stock), photoKeys: newKeys.length ? newKeys : null,
        expectedStock: productId ? loadedStock : null,
        expectedStockRevision: productId ? loadedRevision : null,
      } });
      r = res.data?.saveMarketProduct;
    } catch (e: any) {
      setError(comprarError(e?.networkError ? 'network' : null));
      return;
    }
    if (!r?.success) {
      setError(comprarError(r?.error));
      return;
    }
    navigation.goBack();
  };

  return (
    <ComprarFrame title={productId ? 'Editar producto' : 'Nuevo producto'}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <KitCard icon="camera" title="Fotos" right={<Text style={styles.hint}>{photos.length || existing?.photoUrls?.length || 0}/{MAX_PHOTOS}</Text>}>
          <ScrollView horizontal contentContainerStyle={{ gap: 8 }}>
            {(photos.length ? photos : (existing?.photoUrls || []).map((uri: string) => ({ uri }))).map((p: Photo, i: number) => (
              <View key={`${p.uri}-${i}`} style={styles.photo}>
                <Image source={{ uri: p.uri }} style={styles.photoImage} />
                {p.uploading ? <View style={styles.photoOverlay}><ActivityIndicator color={colors.white} /></View> : null}
                {photos.length ? (
                  <Pressable style={styles.photoRemove} onPress={() => setPhotos((prev) => prev.filter((x) => x !== p))}>
                    <Icon name="x" size={14} color={colors.white} />
                  </Pressable>
                ) : null}
              </View>
            ))}
            {photos.length < MAX_PHOTOS && (
              <Pressable testID="product-add-photo" style={[styles.photo, styles.addPhoto]} onPress={() => { void addPhoto(); }}>
                <Icon name="camera" size={22} color={colors.text.secondary} />
                <Text style={styles.addPhotoText}>{photos.length || !existing ? 'Agregar' : 'Cambiar'}</Text>
              </Pressable>
            )}
          </ScrollView>
          {photoError ? <Text style={styles.error}>{photoError}</Text> : null}
          <Text style={styles.hint}>Muestra el producto real. No incluyas teléfonos, redes sociales ni QR de pago.</Text>
          </KitCard>

          <KitCard icon="edit-3" title="Detalles">
          <TextInput style={styles.input} placeholder="Título" placeholderTextColor={colors.text.light}
            value={title} onChangeText={setTitle} maxLength={100} />
          <TextInput style={[styles.input, { minHeight: 90 }]} multiline placeholder="Descripción: materiales, tamaño, detalles"
            placeholderTextColor={colors.text.light} value={description} onChangeText={setDescription} maxLength={2000} />
          </KitCard>
          <KitCard icon="grid" title="Categoría">
          <CategoryPicker
            categories={
              // A listing whose category the admin has since hidden keeps it.
              existing && !categories.some((c: any) => c.key === existing.category)
                ? [{ key: existing.category, label: existing.categoryLabel || existing.category, group: 'Categoría actual' }, ...categories]
                : categories
            }
            selected={category ? [category] : []}
            onToggle={setCategory}
          />
          {category && ageRules?.categoryKeys.includes(category) ? (
            <AdultsOnlyNote minimumAge={ageRules.minimumAge} audience="listing" />
          ) : null}
          </KitCard>
          <KitCard icon="tag" title="Precio y stock">
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Precio (US$)</Text>
              <TextInput style={styles.input} keyboardType="decimal-pad" placeholder={`0${separators.decimal}00`}
                placeholderTextColor={colors.text.light}
                value={price} onChangeText={(t) => setPrice((prev) => sanitizeAmount(t, 2, undefined, prev))} />
              {rate && priceValue > 0 ? (
                <Text style={styles.hint}>
                  ≈ {formatLocalPrice(priceValue * Number(rate.localPerUsd), rate.currency)} al cambio de hoy
                </Text>
              ) : null}
            </View>
            <View style={{ width: 110 }}>
              <Text style={styles.label}>Stock</Text>
              <TextInput style={styles.input} keyboardType="number-pad" value={stock} onChangeText={setStock} />
            </View>
          </View>
          {priceValue >= 0.5 && typeof data?.marketplaceFeeBps === 'number' ? (
            <Text style={styles.hint}>
              Recibes {formatUsd(priceValue * (1 - data.marketplaceFeeBps / 10_000))} por unidad
              (comisión {formatFeeBps(data.marketplaceFeeBps)}).
            </Text>
          ) : null}
          </KitCard>
          <Text style={[styles.hint, styles.center]}>Confío revisa cada publicación antes de mostrarla.</Text>
        </ScrollView>
        <KitFooter>
          {/* Next to the button, not at the end of a long form, so it is seen. */}
          {error ? <Text style={[styles.error, styles.center]}>{error}</Text> : null}
          <KitButton testID="product-submit" label="Enviar a revisión" icon="send"
            disabled={!valid || uploading} loading={saving} onPress={() => { void submit(); }} />
        </KitFooter>
      </KeyboardAvoidingView>
    </ComprarFrame>
  );
};

export default MarketProductEditScreen;

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 32 },
  center: { textAlign: 'center' },
  label: { fontSize: 13, fontWeight: '600', color: colors.text.secondary },
  hint: { fontSize: 12, color: colors.text.secondary },
  input: { backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 11, fontSize: 15, color: colors.text.primary },
  photo: { width: 84, height: 84, borderRadius: 12, overflow: 'hidden', backgroundColor: colors.neutralDark },
  photoImage: { width: '100%', height: '100%' },
  photoOverlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.35)', alignItems: 'center', justifyContent: 'center' },
  photoRemove: { position: 'absolute', top: 4, right: 4, width: 22, height: 22, borderRadius: 11, backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center' },
  addPhoto: { alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#D1D5DB', backgroundColor: colors.white },
  addPhotoText: { fontSize: 12, color: colors.text.secondary, marginTop: 4 },
  row: { flexDirection: 'row', gap: 10 },
  error: { color: colors.error.text, fontSize: 14 },
});
