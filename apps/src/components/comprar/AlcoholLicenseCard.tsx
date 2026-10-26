import React, { useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation } from '@apollo/client';
import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';
import { pickFromLibrary } from '../../services/systemPicker';
import { SUBMIT_ALCOHOL_LICENSE, comprarError, uploadMarketPhoto, type AlcoholLicense } from '../../services/comprar';
import { KitButton } from './kit';

const PHOTO_MAX_SIDE = 2000;

// "2028-10-26" → "26/10/2028" (a date-only value: no timezone shift).
const formatDate = (iso: string) => {
  const [y, m, d] = iso.split('-');
  return d && m && y ? `${d}/${m}/${y}` : iso;
};

/**
 * The store's municipal alcohol licence (Bolivia's Ley 259, art. 4): needed
 * before listing in Vinos, cervezas y licores. A photo goes to Confío, who
 * approves it with its expiry date.
 */
export const AlcoholLicenseCard = ({ license, onSubmitted }: {
  license: AlcoholLicense | null;
  onSubmitted: () => void;
}) => {
  const [submit] = useMutation(SUBMIT_ALCOHOL_LICENSE);
  const [number, setNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = license?.status ?? 'none';

  const upload = async () => {
    setError(null);
    const res = await pickFromLibrary({ mediaType: 'photo', selectionLimit: 1, quality: 0.8,
      maxWidth: PHOTO_MAX_SIDE, maxHeight: PHOTO_MAX_SIDE });
    if (res.errorCode) {
      setError(res.errorCode === 'permission'
        ? 'Permite el acceso a tus fotos en Ajustes para subir la licencia.'
        : 'No pudimos abrir tus fotos. Inténtalo de nuevo.');
      return;
    }
    const asset = res.assets?.[0];
    if (!asset?.uri) return;
    setBusy(true);
    try {
      const key = await uploadMarketPhoto(asset.uri, asset.type || 'image/jpeg');
      const r = (await submit({ variables: { photoKey: key, licenseNumber: number.trim() || null } })).data?.submitAlcoholLicense;
      if (!r?.success) throw new Error(r?.error || 'upload_failed');
      onSubmitted();
    } catch (e: any) {
      setError(comprarError(e?.message));
    } finally {
      setBusy(false);
    }
  };

  const line = {
    approved: `Licencia aprobada${license?.expiresOn ? `, vigente hasta el ${formatDate(license.expiresOn)}` : ''}.`,
    pending: 'Recibimos tu licencia. Confío la revisa en 1 a 2 días hábiles.',
    rejected: license?.note || 'No pudimos aprobar tu licencia. Sube una foto clara y vigente.',
    expired: 'Tu licencia venció. Sube la renovada para seguir vendiendo bebidas alcohólicas.',
    none: 'Por ley, para vender bebidas alcohólicas necesitas la licencia de funcionamiento de tu municipio que autorice su venta.',
  }[status];
  const canUpload = status !== 'pending';

  return (
    <View style={styles.card} testID="alcohol-license-card">
      <View style={styles.head}>
        <Icon name={status === 'approved' ? 'check-circle' : 'file-text'} size={18}
          color={status === 'approved' ? colors.successText : colors.warning.text} />
        <Text style={styles.title}>Licencia para vender alcohol</Text>
      </View>
      <Text style={styles.body}>{line}</Text>
      {canUpload && status !== 'approved' ? (
        <TextInput style={styles.input} placeholder="Número de licencia (opcional)" value={number}
          onChangeText={setNumber} maxLength={60} placeholderTextColor={colors.text.light} />
      ) : null}
      {canUpload ? (
        busy ? <ActivityIndicator color={colors.primaryDark} />
          : (
            <KitButton testID="alcohol-license-upload" variant={status === 'approved' ? 'secondary' : 'primary'}
              icon="upload" label={status === 'approved' ? 'Subir licencia renovada' : 'Subir foto de la licencia'}
              onPress={() => { void upload(); }} />
          )
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
};

const styles = StyleSheet.create({
  card: { gap: 10, padding: 14, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  body: { fontSize: 13, color: colors.text.secondary, lineHeight: 19 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.text.primary },
  error: { fontSize: 13, color: colors.error.text },
});
