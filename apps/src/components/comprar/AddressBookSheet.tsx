import React, { useState } from 'react';
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation, useQuery } from '@apollo/client';
import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';
import {
  DELETE_DELIVERY_ADDRESS, DeliveryAddress, GET_DELIVERY_ADDRESSES, SAVE_DELIVERY_ADDRESS, comprarError,
} from '../../services/comprar';
import { KitButton } from './kit';

type Props = {
  visible: boolean;
  selectedId?: string | null;
  /** New addresses start in the store's country and city. */
  countryCode: string;
  city: string;
  onClose: () => void;
  /** An address from the book, or null for "type one just for this order". */
  onSelect: (address: DeliveryAddress | null) => void;
};

const LABELS = ['Casa', 'Trabajo', 'Otro'];
const labelIcon = (a: DeliveryAddress) => (
  a.source === 'recarga' ? 'credit-card'
    : /trabajo|oficina/i.test(a.label) ? 'briefcase'
      : /casa|hogar/i.test(a.label) ? 'home' : 'map-pin'
);

type Draft = {
  id?: string; countryCode: string; label: string; city: string; address: string; phone: string; note: string; makeDefault: boolean;
};

/**
 * Mis direcciones: the buyer's saved addresses for this account, plus the
 * Recarga address (read-only: it is the one Recarga verified, changed there).
 */
export const AddressBookSheet = ({ visible, selectedId, countryCode, city, onClose, onSelect }: Props) => {
  const { data, loading, refetch } = useQuery(GET_DELIVERY_ADDRESSES, { fetchPolicy: 'cache-and-network', skip: !visible });
  const addresses: DeliveryAddress[] = data?.myDeliveryAddresses || [];
  const [save, { loading: saving }] = useMutation(SAVE_DELIVERY_ADDRESS);
  const [remove] = useMutation(DELETE_DELIVERY_ADDRESS);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startNew = (from?: DeliveryAddress) => {
    setError(null);
    setDraft(from && from.editable
      // An edit keeps the entry's own country (a Caracas address stays in VE).
      ? { id: from.id, countryCode: from.countryCode, label: from.label, city: from.city, address: from.address,
        phone: from.phone, note: from.note, makeDefault: from.isDefault }
      : { countryCode, label: 'Casa', city: from?.city || city, address: from?.address || '', phone: from?.phone || '',
        note: '', makeDefault: false });
  };

  const submit = async () => {
    if (!draft) return;
    setError(null);
    try {
      const res = await save({ variables: {
        addressId: draft.id || null, label: draft.label, countryCode: draft.countryCode, city: draft.city, address: draft.address,
        phone: draft.phone, note: draft.note, makeDefault: draft.makeDefault,
      } });
      const r = res.data?.saveDeliveryAddress;
      if (!r?.success) { setError(comprarError(r?.error)); return; }
      await refetch().catch(() => {});
      setDraft(null);
      // Only an address this store delivers to becomes the order's address.
      if ((r.address?.countryCode || '').toUpperCase() === countryCode.toUpperCase()) onSelect(r.address);
    } catch (e: any) {
      setError(comprarError(e?.networkError ? 'network' : null));
    }
  };

  const confirmDelete = (a: DeliveryAddress) => {
    Alert.alert('Borrar dirección', `¿Borrar «${a.label || a.address}»?`, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Borrar', style: 'destructive', onPress: async () => {
        try {
          const res = await remove({ variables: { addressId: a.id } });
          if (!res.data?.deleteDeliveryAddress?.success) setError(comprarError(res.data?.deleteDeliveryAddress?.error));
        } catch {
          setError(comprarError('network'));
        }
        await refetch().catch(() => {});
      } },
    ]);
  };

  const close = () => { setDraft(null); setError(null); onClose(); };
  const canSave = !!draft && draft.address.trim().length >= 8 && draft.phone.replace(/\D/g, '').length >= 7
    && draft.city.trim().length >= 2;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            {draft ? (
              <Pressable onPress={() => { setDraft(null); setError(null); }} hitSlop={10} accessibilityLabel="Volver">
                <Icon name="chevron-left" size={22} color={colors.text.primary} />
              </Pressable>
            ) : null}
            <Text style={styles.title}>{draft ? (draft.id ? 'Editar dirección' : 'Nueva dirección') : 'Mis direcciones'}</Text>
            <Pressable onPress={close} hitSlop={10} accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.text.secondary} />
            </Pressable>
          </View>

          {draft ? (
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.form}>
              <View style={styles.chips}>
                {LABELS.map((l) => (
                  <Pressable key={l} onPress={() => setDraft({ ...draft, label: l })}
                    style={[styles.chip, draft.label === l && styles.chipOn]} accessibilityRole="radio"
                    accessibilityState={{ checked: draft.label === l }}>
                    <Text style={[styles.chipText, draft.label === l && styles.chipTextOn]}>{l}</Text>
                  </Pressable>
                ))}
              </View>
              <Field icon="map" placeholder="Ciudad" value={draft.city} onChangeText={(t) => setDraft({ ...draft, city: t })} />
              <Field icon="home" placeholder="Dirección (calle, número, zona)" value={draft.address}
                onChangeText={(t) => setDraft({ ...draft, address: t })} />
              <Field icon="phone" placeholder="Teléfono para el repartidor" keyboardType="phone-pad" value={draft.phone}
                onChangeText={(t) => setDraft({ ...draft, phone: t })} />
              <Field icon="message-square" placeholder="Referencia (opcional)" value={draft.note}
                onChangeText={(t) => setDraft({ ...draft, note: t })} />
              <View style={styles.switchRow}>
                <Text style={styles.switchText}>Usar por defecto</Text>
                <Switch value={draft.makeDefault} onValueChange={(v) => setDraft({ ...draft, makeDefault: v })} />
              </View>
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <KitButton testID="address-save" label="Guardar dirección" disabled={!canSave} loading={saving}
                onPress={() => { void submit(); }} />
            </ScrollView>
          ) : (
            <ScrollView contentContainerStyle={styles.list}>
              {loading && !addresses.length ? <ActivityIndicator color={colors.primaryDark} style={{ marginVertical: 24 }} /> : null}
              {addresses.map((a) => {
                const on = a.id === selectedId;
                // This store delivers in its own country only.
                const usable = (a.countryCode || '').toUpperCase() === countryCode.toUpperCase();
                return (
                  <Pressable key={a.id} testID={`address-${a.id}`} style={[styles.row, on && styles.rowOn, !usable && styles.rowOff]}
                    disabled={!usable} onPress={() => { onSelect(a); }} accessibilityRole="radio"
                    accessibilityState={{ checked: on, disabled: !usable }}>
                    <View style={[styles.rowIcon, on && styles.rowIconOn]}>
                      <Icon name={labelIcon(a)} size={16} color={on ? colors.white : colors.primaryDeep} />
                    </View>
                    <View style={{ flex: 1, gap: 2 }}>
                      <View style={styles.rowTop}>
                        <Text style={styles.rowLabel} numberOfLines={1}>{a.label || 'Dirección'}</Text>
                        {a.isDefault ? <Text style={styles.badge}>Por defecto</Text> : null}
                        {a.source === 'recarga' ? <Text style={styles.badge}>De Recarga</Text> : null}
                      </View>
                      <Text style={styles.rowAddress} numberOfLines={2}>{a.address}</Text>
                      <Text style={styles.rowMeta} numberOfLines={1}>
                        {usable ? `${a.city}${a.phone ? ` · ${a.phone}` : ''}` : `${a.city} · otro país, esta tienda no entrega allí`}
                      </Text>
                    </View>
                    {a.editable ? (
                      <View style={styles.rowActions}>
                        <Pressable hitSlop={8} onPress={() => startNew(a)} accessibilityLabel="Editar">
                          <Icon name="edit-2" size={16} color={colors.text.secondary} />
                        </Pressable>
                        <Pressable hitSlop={8} onPress={() => confirmDelete(a)} accessibilityLabel="Borrar">
                          <Icon name="trash-2" size={16} color={colors.text.light} />
                        </Pressable>
                      </View>
                    ) : on ? <Icon name="check" size={18} color={colors.primaryDark} /> : null}
                  </Pressable>
                );
              })}
              {!loading && !addresses.length ? (
                <Text style={styles.empty}>Guarda tus direcciones para no escribirlas en cada compra.</Text>
              ) : null}
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <KitButton testID="address-new" label="Agregar dirección" icon="plus" variant="secondary" onPress={() => startNew()} />
              <KitButton label="Escribir una solo para este pedido" variant="ghost" onPress={() => onSelect(null)} />
            </ScrollView>
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const Field = ({ icon, ...props }: { icon: string } & React.ComponentProps<typeof TextInput>) => (
  <View style={styles.field}>
    <Icon name={icon} size={16} color={colors.text.light} />
    <TextInput style={styles.fieldInput} placeholderTextColor={colors.text.light} {...props} />
  </View>
);

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 28, maxHeight: '90%' },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: 10 },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 12 },
  title: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.textFlat },
  list: { gap: 10, paddingBottom: 8 },
  form: { gap: 10, paddingBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  rowOn: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  rowOff: { opacity: 0.5 },
  rowIcon: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  rowIconOn: { backgroundColor: colors.primaryDark },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  rowLabel: { fontSize: 15, fontWeight: '700', color: colors.textFlat, flexShrink: 1 },
  badge: { fontSize: 11, fontWeight: '700', color: colors.primaryDeep, backgroundColor: colors.white, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1, overflow: 'hidden', borderWidth: 1, borderColor: colors.primaryMuted },
  rowAddress: { fontSize: 14, color: colors.text.primary },
  rowMeta: { fontSize: 12, color: colors.text.secondary },
  rowActions: { flexDirection: 'row', gap: 14 },
  empty: { fontSize: 14, color: colors.text.secondary, textAlign: 'center', marginVertical: 12 },
  error: { fontSize: 14, color: colors.error.text, textAlign: 'center' },
  chips: { flexDirection: 'row', gap: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.textFlat, borderColor: colors.textFlat },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  chipTextOn: { color: colors.white },
  field: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12 },
  fieldInput: { flex: 1, paddingVertical: 12, fontSize: 15, color: colors.text.primary },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  switchText: { fontSize: 14, color: colors.text.primary },
});
