import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import Svg, { Circle, Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import { useApolloClient } from '@apollo/client';
import { useFocusEffect, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { CountryFlag } from '../components/CountryFlag';
import { EmptyState } from '../components/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { AddPayoutMethodModal } from '../components/AddPayoutMethodModal';
import { useOwnVeCedula } from '../components/agenda/VeAgendaPicker';
import { useAccount } from '../contexts/AccountContext';
import { DELETE_BANK_INFO, GET_USER_BANK_ACCOUNTS, SET_DEFAULT_BANK_INFO } from '../apollo/queries';
import { VE_BANKS } from '../services/vePagoMovilTopUp';
import { fetchLocalDestination, resolveLocalDestination } from '../services/localMoney';
import {
  AGENDA_ENTRIES,
  AGENDA_METHODS,
  AGENDA_RECENTS,
  AgendaEntry,
  AgendaMethod,
  LOCAL_FIELD_COPY,
  AgendaRecent,
  AgendaRelationship,
  BANK_INFO_RAIL,
  DELETE_AGENDA_ENTRY,
  RAIL_NAMES,
  SAVE_DESTINATION_TO_AGENDA,
  SAVE_VE_AGENDA_ENTRY,
  UPDATE_AGENDA_ENTRY,
  VE_PAGOMOVIL_RAIL,
  localVePhone,
  useAgendaAccountKey,
} from '../services/agenda';

const GENERIC = 'Error de conexión. Intenta de nuevo.';
const COUNTRY_NAMES: Record<string, string> = {
  VE: 'Venezuela', CO: 'Colombia', MX: 'México', AR: 'Argentina', BR: 'Brasil', PE: 'Perú', BO: 'Bolivia',
  CL: 'Chile', EC: 'Ecuador', US: 'Estados Unidos', DO: 'República Dominicana', PA: 'Panamá',
};
const RAIL_ICONS: Record<string, string> = {
  bank_info: 'bank', ve_pagomovil: 'cellphone', co_breb: 'key-variant', mx_clabe: 'bank-transfer',
  ar_cvu: 'bank-transfer', br_pix: 'lightning-bolt',
};

type Tab = 'own' | 'third_party';
type Bank = { code: string; name: string };
type Banner = { message: string; variant: 'error' | 'success' } | null;
type ListItem =
  | { kind: 'country'; key: string; country: string }
  | { kind: 'entry'; key: string; entry: AgendaEntry }
  | { kind: 'recentsTitle'; key: string }
  | { kind: 'recent'; key: string; recent: AgendaRecent };

interface VeForm {
  id?: string;
  label: string;
  relationship: AgendaRelationship;
  holderName: string;
  cedula: string;
  phone: string;
  bank: Bank | null;
}

const byCountry = (a: AgendaEntry, b: AgendaEntry) =>
  (a.country || 'ZZ').localeCompare(b.country || 'ZZ') || Number(b.isDefault) - Number(a.isDefault)
  || a.label.localeCompare(b.label);

/**
 * Agenda: every saved account, the person's own ("Mías") and other people's.
 * Everything is managed here, in place: withdrawal accounts (Mis cuentas) with
 * the same form Mis cuentas uses, Venezuelan Pago Móvil accounts, and local-send
 * recipients (send, rename, delete); past recipients can be saved in one tap.
 */
export default function AgendaScreen() {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  const { activeAccount } = useAccount();
  const accountKey = useAgendaAccountKey();
  const seq = useRef(0);
  const isEmployee = activeAccount?.isEmployee || false;
  const canManage = !isEmployee || Boolean((activeAccount as any)?.employeePermissions?.manageBankAccounts);

  const [tab, setTab] = useState<Tab>('own');
  const [entries, setEntries] = useState<AgendaEntry[]>([]);
  const [recents, setRecents] = useState<AgendaRecent[]>([]);
  const [bankInfos, setBankInfos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  const [addSheet, setAddSheet] = useState(false);
  const [bankModal, setBankModal] = useState<{
    editing: any | null; countryCode?: string; paymentMethodId?: string | null;
  } | null>(null);
  // The add flow: country → method → (here) the account, or a hand-off to the
  // Pago Móvil form or the withdrawal-account form.
  const [methods, setMethods] = useState<AgendaMethod[] | null>(null);
  const [methodsFailed, setMethodsFailed] = useState(false);
  const [addCountry, setAddCountry] = useState<string | null>(null);
  const [localForm, setLocalForm] = useState<{
    method: AgendaMethod; value: string; label: string; error: string;
  } | null>(null);
  const [veForm, setVeForm] = useState<VeForm | null>(null);
  const [veError, setVeError] = useState('');
  const [saving, setSaving] = useState(false);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [bankPicker, setBankPicker] = useState(false);
  const [editEntry, setEditEntry] = useState<{ entry: AgendaEntry; label: string } | null>(null);
  // "Es mía" on a Pago Móvil account is this cédula, locked.
  const ownCedula = useOwnVeCedula();

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoadFailed(false);
    if (!accountKey) {
      setEntries([]);
      setRecents([]);
      setBankInfos([]);
      return;
    }
    try {
      const [list, recent, bankList] = await Promise.all([
        client.query({ query: AGENDA_ENTRIES, fetchPolicy: 'network-only' }),
        client.query({ query: AGENDA_RECENTS, fetchPolicy: 'network-only' }).catch(() => null),
        client.query({ query: GET_USER_BANK_ACCOUNTS, fetchPolicy: 'network-only' }).catch(() => null),
      ]);
      if (mine !== seq.current) return;
      setEntries(list.data?.agendaEntries || []);
      setRecents(recent?.data?.agendaRecents || []);
      setBankInfos(bankList?.data?.userBankAccounts || []);
    } catch {
      if (mine === seq.current) setLoadFailed(true);
    } finally {
      if (mine === seq.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [client, accountKey]);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  // An account switch (even while this screen is in the background) drops the
  // previous account's rows and open forms at once, and voids answers in flight.
  useEffect(() => {
    seq.current += 1;
    setEntries([]);
    setRecents([]);
    setBankInfos([]);
    setLoading(true);
    setAddSheet(false);
    setBankModal(null);
    setVeForm(null);
    setEditEntry(null);
    // Reload for the new account (this also supersedes a focus load that
    // started on the same render).
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountKey]);

  // A modal opened while another is still animating closed never shows on iOS:
  // the add sheet hands over to the next form after its fade-out.
  const afterAddSheet = (next: () => void) => {
    setAddSheet(false);
    setTimeout(next, SHEET_FADE_MS);
  };

  const loadMethods = async () => {
    setMethodsFailed(false);
    try {
      const { data } = await client.query({ query: AGENDA_METHODS, fetchPolicy: 'network-only' });
      setMethods(data?.agendaMethods || []);
    } catch {
      setMethodsFailed(true);
    }
  };

  const openAdd = () => {
    setAddCountry(null);
    setLocalForm(null);
    setAddSheet(true);
    void loadMethods();
  };

  const countries = useMemo(() => {
    const codes = Array.from(new Set((methods || []).map(m => m.country)));
    return codes.sort((a, b) => (COUNTRY_NAMES[a] || a).localeCompare(COUNTRY_NAMES[b] || b, 'es'));
  }, [methods]);

  const pickMethod = (method: AgendaMethod) => {
    if (method.status !== 'live') return;
    if (method.kind === VE_PAGOMOVIL_RAIL) {
      afterAddSheet(() => { void openVeForm(undefined, method.allowsThirdParty ? tab : 'own'); });
    } else if (method.kind === BANK_INFO_RAIL) {
      afterAddSheet(() => setBankModal({
        editing: null, countryCode: method.country, paymentMethodId: method.paymentMethodId,
      }));
    } else {
      setLocalForm({
        method, value: '', label: '', error: '',
      });
    }
  };

  const submitLocal = async () => {
    if (!localForm || saving) return;
    if (!localForm.value.trim()) {
      setLocalForm({ ...localForm, error: `Escribe la ${LOCAL_FIELD_COPY[localForm.method.id]?.label || 'cuenta'}.` });
      return;
    }
    setSaving(true);
    setLocalForm({ ...localForm, error: '' });
    try {
      // The same check a send runs: the holder is looked up before it is kept.
      let destination = await resolveLocalDestination(localForm.method.id, localForm.value.trim(), 20000);
      // Some rails answer the holder check later: wait for it (bounded), so
      // a key that does not exist is never saved.
      for (let tries = 0; destination.verification === 'pending' && tries < PENDING_POLLS; tries += 1) {
        await new Promise(resolve => setTimeout(resolve, PENDING_POLL_MS));
        destination = await fetchLocalDestination(destination.id);
      }
      if (destination.verification === 'not_found') {
        setLocalForm({ ...localForm, error: 'No encontramos esta cuenta. Revisa los datos.' });
        return;
      }
      const { data } = await client.mutate({
        mutation: SAVE_DESTINATION_TO_AGENDA,
        variables: { destinationId: destination.id, label: localForm.label.trim() },
        fetchPolicy: 'no-cache',
      });
      const result = data?.saveDestinationToAgenda;
      if (!result?.success) {
        setLocalForm({ ...localForm, error: result?.errors?.[0] || GENERIC });
        return;
      }
      setAddSheet(false);
      setLocalForm(null);
      // Whose it is came from the holder check: show it where it landed.
      const landed: AgendaRelationship = result.entry?.relationship === 'own' ? 'own' : 'third_party';
      setTab(landed);
      // Saved either way; a holder not confirmed yet is checked again before
      // every send, and the person is told so.
      setBanner(destination.verification === 'verified' && destination.holderName ? {
        variant: 'success',
        message: landed === 'own' ? 'Está a tu nombre: la guardamos en «Mías»'
          : `${destination.holderName} guardada en «Otras personas»`,
      } : {
        variant: 'success',
        message: 'Guardada. Aún no confirmamos el titular: lo verificamos antes de cada envío.',
      });
      await load();
    } catch (error: any) {
      setLocalForm({ ...localForm, error: error?.message || GENERIC });
    } finally {
      setSaving(false);
    }
  };

  const own = useMemo(() => entries.filter(e => e.relationship === 'own').sort(byCountry), [entries]);
  const others = useMemo(() => entries.filter(e => e.relationship !== 'own').sort(byCountry), [entries]);

  const items = useMemo<ListItem[]>(() => {
    const rows: ListItem[] = [];
    let country: string | null = null;
    for (const entry of tab === 'own' ? own : others) {
      if (entry.country !== country) {
        country = entry.country;
        rows.push({ kind: 'country', key: `c-${entry.country}-${entry.id}`, country: entry.country });
      }
      rows.push({ kind: 'entry', key: entry.id, entry });
    }
    if (tab === 'third_party' && recents.length) {
      rows.push({ kind: 'recentsTitle', key: 'recents' });
      recents.forEach(recent => rows.push({ kind: 'recent', key: `r-${recent.destinationId}`, recent }));
    }
    return rows;
  }, [tab, own, others, recents]);

  // ── actions ───────────────────────────────────────────────────────────────

  const run = async (mutation: () => Promise<any>, field: string, success: string) => {
    try {
      const { data } = await mutation();
      const result = data?.[field];
      if (!result?.success) {
        setBanner({ variant: 'error', message: result?.errors?.[0] || result?.error || GENERIC });
        return false;
      }
      setBanner({ variant: 'success', message: success });
      await load();
      return true;
    } catch {
      setBanner({ variant: 'error', message: GENERIC });
      return false;
    }
  };

  const confirmDelete = (entry: AgendaEntry) => Alert.alert('Eliminar de tu Agenda', `¿Eliminar ${entry.label}?`, [
    { text: 'Cancelar', style: 'cancel' },
    {
      text: 'Eliminar', style: 'destructive',
      onPress: () => {
        void (entry.rail === BANK_INFO_RAIL
          ? run(() => client.mutate({ mutation: DELETE_BANK_INFO, variables: { bankInfoId: entry.bankInfoId } }),
            'deleteBankInfo', 'Cuenta eliminada')
          : run(() => client.mutate({ mutation: DELETE_AGENDA_ENTRY, variables: { id: entry.id } }),
            'deleteAgendaEntry', 'Cuenta eliminada'));
      },
    },
  ]);

  const setDefault = (entry: AgendaEntry) => {
    void run(() => client.mutate({ mutation: SET_DEFAULT_BANK_INFO, variables: { bankInfoId: entry.bankInfoId } }),
      'setDefaultBankInfo', 'Cuenta marcada como predeterminada');
  };

  const loadBanks = async () => {
    try {
      const { data } = await client.query({ query: VE_BANKS, fetchPolicy: banks.length ? 'cache-first' : 'network-only' });
      const list: Bank[] = data?.vePagomovilBanks || [];
      setBanks(list);
      return list;
    } catch {
      return banks;
    }
  };

  const openVeForm = async (entry?: AgendaEntry, relationship: AgendaRelationship = tab) => {
    setVeError('');
    const list = await loadBanks();
    setVeForm(entry ? {
      id: entry.id, label: entry.label, relationship: entry.relationship, holderName: entry.holderName,
      cedula: entry.cedula || '', phone: localVePhone(entry.phone),
      bank: list.find(b => b.code === entry.bankCode) || null,
    } : {
      // "Es mía" needs a verified Venezuelan cédula.
      label: '', relationship: relationship === 'own' && !ownCedula ? 'third_party' : relationship,
      holderName: '', cedula: '', phone: '', bank: null,
    });
  };

  const edit = (entry: AgendaEntry) => {
    if (entry.rail === BANK_INFO_RAIL) {
      const editing = bankInfos.find(row => String(row.id) === String(entry.bankInfoId));
      if (!editing) {
        setBanner({ variant: 'error', message: 'No pudimos abrir esta cuenta. Desliza para actualizar.' });
        return;
      }
      setBankModal({ editing });
      return;
    }
    if (entry.rail === VE_PAGOMOVIL_RAIL) {
      void openVeForm(entry);
      return;
    }
    setEditEntry({ entry, label: entry.label });
  };

  const send = (entry: AgendaEntry) =>
    navigation.navigate('LocalSend', { methodId: entry.rail, destinationId: entry.destinationId });

  const submitVe = async () => {
    if (!veForm || saving) return;
    if (!veForm.bank) {
      setVeError('Elige el banco.');
      return;
    }
    setSaving(true);
    setVeError('');
    try {
      const { data } = await client.mutate({
        mutation: SAVE_VE_AGENDA_ENTRY,
        variables: {
          // "own" means the verified cédula: the server fills it in.
          id: veForm.id, label: veForm.label.trim(), relationship: veForm.relationship === 'own' ? 'own' : null,
          holderName: veForm.holderName.trim(), cedula: veForm.relationship === 'own' ? '' : veForm.cedula.trim(),
          phone: veForm.phone.trim(),
          bankCode: veForm.bank.code,
        },
        fetchPolicy: 'no-cache',
      });
      const result = data?.saveVePagomovilAgendaEntry;
      if (!result?.success) {
        setVeError(result?.errors?.[0] || GENERIC);
        return;
      }
      setVeForm(null);
      setTab(result.entry?.relationship === 'own' ? 'own' : 'third_party');
      setBanner({ variant: 'success', message: veForm.id ? 'Cuenta actualizada' : 'Cuenta guardada en tu Agenda' });
      await load();
    } catch {
      setVeError(GENERIC);
    } finally {
      setSaving(false);
    }
  };

  const submitEdit = async () => {
    if (!editEntry || saving) return;
    setSaving(true);
    const ok = await run(() => client.mutate({
      mutation: UPDATE_AGENDA_ENTRY,
      variables: { id: editEntry.entry.id, label: editEntry.label.trim() },
    }), 'updateAgendaEntry', 'Cuenta actualizada');
    setSaving(false);
    if (ok) setEditEntry(null);
  };

  // One tap: whose account it is comes from its holder check.
  const saveRecent = async (recent: AgendaRecent) => {
    if (saving) return;
    setSaving(true);
    await run(() => client.mutate({
      mutation: SAVE_DESTINATION_TO_AGENDA, variables: { destinationId: recent.destinationId },
    }), 'saveDestinationToAgenda', 'Guardada en tu Agenda');
    setSaving(false);
  };

  // ── rendering ─────────────────────────────────────────────────────────────

  const renderEntry = (entry: AgendaEntry) => {
    const icon = RAIL_ICONS[entry.rail] || 'bank';
    const accent = entry.rail === BANK_INFO_RAIL ? colors.accent : entry.rail === VE_PAGOMOVIL_RAIL
      ? colors.primaryDark : colors.secondary;
    // Withdrawal accounts read like Mis cuentas (holder · summary); the label
    // already names the method, so its masked subtitle would only repeat it.
    const bankInfo = entry.rail === BANK_INFO_RAIL
      ? bankInfos.find(row => String(row.id) === String(entry.bankInfoId)) : null;
    const detail = bankInfo
      ? [bankInfo.accountHolderName, bankInfo.summaryText].filter(Boolean).join('  ·  ')
      : [entry.relationship === 'own' ? '' : entry.holderName, entry.subtitle].filter(Boolean).join('  ·  ');
    return (
      <View style={[styles.card, entry.isDefault && styles.cardDefault]}>
        <View style={[styles.cardIconChip, { backgroundColor: accent + '18' }]}>
          <MCIcon name={icon} size={20} color={accent} />
        </View>
        <View style={styles.cardInner}>
          <View style={styles.cardRow}>
            <CountryFlag iso={entry.country} size={18} style={styles.cardFlag} />
            <Text style={styles.cardTitle} numberOfLines={1}>{entry.label}</Text>
            <View style={styles.cardActions}>
              <TouchableOpacity onPress={() => edit(entry)} style={styles.actionBtn} accessibilityRole="button"
                accessibilityLabel={`Editar ${entry.label}`} hitSlop={HIT}>
                <Icon name="edit-2" size={15} color={colors.accent} />
              </TouchableOpacity>
              {entry.rail === BANK_INFO_RAIL && !entry.isDefault ? (
                <TouchableOpacity onPress={() => setDefault(entry)} style={styles.actionBtn} accessibilityRole="button"
                  accessibilityLabel="Marcar como predeterminada" hitSlop={HIT}>
                  <Icon name="star" size={15} color={colors.warning.icon} />
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity onPress={() => confirmDelete(entry)} style={styles.actionBtn} accessibilityRole="button"
                accessibilityLabel={`Eliminar ${entry.label}`} hitSlop={HIT}>
                <Icon name="trash-2" size={15} color={colors.error.icon} />
              </TouchableOpacity>
            </View>
          </View>
          <View style={styles.cardRow2}>
            <View style={[styles.typePill, { backgroundColor: accent + '18' }]}>
              <Text style={[styles.typePillText, { color: accent }]}>{RAIL_NAMES[entry.rail] || 'Cuenta'}</Text>
            </View>
            {entry.isDefault ? (
              <View style={styles.defaultBadge}><Text style={styles.defaultText}>Predeterminada</Text></View>
            ) : null}
          </View>
          {detail ? <Text style={styles.cardDetail} numberOfLines={1} ellipsizeMode="middle">{detail}</Text> : null}
          {entry.destinationId ? (
            <TouchableOpacity onPress={() => send(entry)} style={styles.sendChip} accessibilityRole="button"
              accessibilityLabel={`Enviar a ${entry.label}`}>
              <Icon name="send" size={13} color={colors.white} />
              <Text style={styles.sendChipText}>Enviar</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>
    );
  };

  const renderItem = ({ item }: { item: ListItem }) => {
    if (item.kind === 'country') {
      return <Text style={styles.countryHeader}>{COUNTRY_NAMES[item.country] || item.country || 'Otros'}</Text>;
    }
    if (item.kind === 'recentsTitle') {
      return (
        <View style={styles.recentsHeader}>
          <Text style={styles.countryHeader}>Recientes de tus envíos</Text>
          <Text style={styles.recentsHint}>Guárdalos para encontrarlos siempre aquí.</Text>
        </View>
      );
    }
    if (item.kind === 'recent') {
      const { recent } = item;
      return (
        <View style={[styles.card, styles.recentCard]}>
          <CountryFlag iso={recent.country} size={20} style={styles.recentFlag} />
          <View style={styles.cardInner}>
            <Text style={styles.cardTitle} numberOfLines={1}>{recent.holderName || recent.label}</Text>
            <Text style={styles.cardDetail} numberOfLines={1}>
              {[RAIL_NAMES[recent.rail], recent.holderName ? recent.label : ''].filter(Boolean).join('  ·  ')}
            </Text>
          </View>
          <TouchableOpacity onPress={() => { void saveRecent(recent); }} disabled={saving} style={styles.saveChip} accessibilityRole="button"
            accessibilityLabel={`Guardar ${recent.label}`}>
            <Icon name="bookmark" size={13} color={colors.primaryDark} />
            <Text style={styles.saveChipText}>Guardar</Text>
          </TouchableOpacity>
        </View>
      );
    }
    return renderEntry(item.entry);
  };

  const empty = tab === 'own' ? (
    <EmptyState icon="credit-card" title="Aún no tienes cuentas guardadas"
      subtitle="Guarda tus cuentas bancarias, billeteras y Pago Móvil para recargar y retirar más rápido."
      actionLabel="Agregar cuenta" onAction={openAdd} />
  ) : (
    <EmptyState icon="users" title="Aún no guardas a nadie"
      subtitle="Guarda las cuentas de las personas a quienes envías dinero para no escribirlas cada vez."
      actionLabel="Agregar persona" onAction={openAdd} />
  );

  if (!canManage) {
    return (
      <View style={styles.container}>
        <Header navigation={navigation} title="Agenda" backgroundColor={colors.heroField} isLight showBackButton />
        <EmptyState icon="lock" title="Agenda del negocio"
          subtitle="Las cuentas del negocio las gestiona el equipo administrativo." />
      </View>
    );
  }

  const listEmpty = !items.some(row => row.kind === 'entry');

  return (
    // Header pads for the status bar itself.
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Agenda"
        backgroundColor={colors.heroField}
        isLight
        showBackButton
        rightAccessory={(
          <TouchableOpacity onPress={openAdd} style={styles.addHeaderButton} hitSlop={HIT}
            accessibilityRole="button" accessibilityLabel="Agregar cuenta">
            <Icon name="plus" size={20} color={colors.white} />
          </TouchableOpacity>
        )}
      />

      <View style={styles.brandField}>
        <Svg style={StyleSheet.absoluteFill}>
          <Defs>
            <LinearGradient id="agendaField" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={colors.heroField} />
              <Stop offset="1" stopColor={colors.heroFieldDark} />
            </LinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#agendaField)" />
          <Circle cx="105%" cy="18%" r="80" stroke={colors.white} strokeWidth="20" strokeOpacity="0.10" fill="none" />
        </Svg>
        <View style={styles.fieldInner}>
          <Text style={styles.fieldEyebrow}>TU AGENDA</Text>
          <Text style={styles.fieldTitle}>Tus cuentas y las de tu gente</Text>
          <Text style={styles.fieldSubtitle}>Listas para recargar, retirar y enviar sin volver a escribirlas.</Text>
          <View style={styles.tabs}>
            {(['own', 'third_party'] as Tab[]).map(option => {
              const active = tab === option;
              const count = option === 'own' ? own.length : others.length;
              return (
                <TouchableOpacity key={option} onPress={() => setTab(option)} accessibilityRole="tab"
                  accessibilityState={{ selected: active }} style={[styles.tab, active && styles.tabActive]}>
                  <Text style={[styles.tabText, active && styles.tabTextActive]}>
                    {option === 'own' ? 'Mías' : 'Otras personas'}{loading ? '' : ` · ${count}`}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      </View>

      {banner ? (
        <InlineBanner message={banner.message} variant={banner.variant} onDismiss={() => setBanner(null)}
          autoHideMs={banner.variant === 'success' ? 2500 : undefined}
          style={{ marginHorizontal: 16, marginTop: 16, marginBottom: 0 }} />
      ) : null}

      {loading ? (
        <ActivityIndicator style={styles.loader} color={colors.primary} />
      ) : loadFailed ? (
        <EmptyState icon="wifi-off" title="No pudimos cargar tu Agenda" subtitle="Revisa tu conexión e intenta de nuevo."
          actionLabel="Reintentar" onAction={() => { void load(); }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={item => item.key}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          showsVerticalScrollIndicator={false}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          refreshControl={(
            <RefreshControl refreshing={refreshing} colors={[colors.primary]} tintColor={colors.primary}
              onRefresh={() => { setRefreshing(true); void load(); }} />
          )}
          ListHeaderComponent={listEmpty ? empty : null}
          ListFooterComponent={listEmpty ? null : (
            <TouchableOpacity style={styles.addMoreButton} onPress={openAdd} accessibilityRole="button">
              <Icon name="plus-circle" size={18} color={colors.primary} />
              <Text style={styles.addMoreText}>Agregar cuenta</Text>
            </TouchableOpacity>
          )}
        />
      )}

      {/* ── Add an account: country → method → details ── */}
      <Modal visible={addSheet} animationType="slide" presentationStyle="pageSheet"
        onRequestClose={() => { if (!saving) setAddSheet(false); }}>
        <KeyboardAvoidingView style={styles.sheetPage} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.pageHeader}>
            {addCountry ? (
              <TouchableOpacity accessibilityRole="button" accessibilityLabel="Atrás" hitSlop={HIT} disabled={saving}
                onPress={() => (localForm ? setLocalForm(null) : setAddCountry(null))} style={styles.backButton}>
                <Icon name="chevron-left" size={24} color={colors.text.primary} />
              </TouchableOpacity>
            ) : null}
            <Text style={[styles.pageTitle, styles.flex]} numberOfLines={1}>
              {localForm ? localForm.method.title : addCountry ? (COUNTRY_NAMES[addCountry] || addCountry) : 'Agregar cuenta'}
            </Text>
            <TouchableOpacity onPress={() => setAddSheet(false)} disabled={saving} accessibilityRole="button"
              accessibilityLabel="Cerrar" hitSlop={HIT}>
              <Icon name="x" size={24} color={colors.text.primary} />
            </TouchableOpacity>
          </View>

          {!addCountry ? (
            methods === null ? (
              methodsFailed ? (
                <EmptyState icon="wifi-off" title="No pudimos cargar los países" actionLabel="Reintentar"
                  onAction={() => { void loadMethods(); }} />
              ) : <ActivityIndicator style={styles.loader} color={colors.primary} />
            ) : (
              <FlatList
                data={countries}
                keyExtractor={item => item}
                initialNumToRender={20}
                maxToRenderPerBatch={10}
                windowSize={21}
                ListHeaderComponent={<Text style={styles.stepHint}>¿De qué país es la cuenta?</Text>}
                renderItem={({ item }) => (
                  <TouchableOpacity style={styles.countryRow} accessibilityRole="button" onPress={() => setAddCountry(item)}>
                    <CountryFlag iso={item} size={24} />
                    <Text style={[styles.optionTitle, styles.flex]}>{COUNTRY_NAMES[item] || item}</Text>
                    <Icon name="chevron-right" size={18} color={colors.text.light} />
                  </TouchableOpacity>
                )}
              />
            )
          ) : !localForm ? (
            <ScrollView contentContainerStyle={styles.pageContent}>
              <Text style={[styles.stepHint, styles.stepHintFlush]}>¿Qué tipo de cuenta?</Text>
              {(methods || []).filter(m => m.country === addCountry).map(method => {
                const live = method.status === 'live';
                return (
                  <TouchableOpacity key={method.id} style={[styles.option, !live && styles.disabled]} disabled={!live}
                    onPress={() => pickMethod(method)} accessibilityRole="button">
                    <View style={styles.optionIcon}>
                      <MCIcon name={RAIL_ICONS[method.kind === 'local' ? method.id : method.kind] || 'bank'} size={22}
                        color={colors.primaryDark} />
                    </View>
                    <View style={styles.flex}>
                      <Text style={styles.optionTitle}>{method.title}</Text>
                      <Text style={styles.optionSubtitle} numberOfLines={2}>
                        {live ? method.subtitle : 'Aún no disponible para tu cuenta'}
                      </Text>
                      <Text style={[styles.ownership, method.allowsThirdParty && styles.ownershipOpen]}>
                        {method.allowsThirdParty ? 'Tuya o de otra persona' : 'Solo a tu nombre'}
                      </Text>
                    </View>
                    <Icon name="chevron-right" size={18} color={colors.text.light} />
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          ) : (
            <ScrollView contentContainerStyle={styles.pageContent} keyboardShouldPersistTaps="handled">
              <Text style={[styles.label, styles.firstLabel]}>{LOCAL_FIELD_COPY[localForm.method.id]?.label || localForm.method.title}</Text>
              <TextInput value={localForm.value} onChangeText={value => setLocalForm({ ...localForm, value, error: '' })}
                placeholder={LOCAL_FIELD_COPY[localForm.method.id]?.placeholder}
                keyboardType={LOCAL_FIELD_COPY[localForm.method.id]?.keyboard || 'default'} autoCapitalize="none"
                placeholderTextColor={colors.textTertiary} style={styles.input} />
              <Text style={styles.fieldHelp}>
                Verificamos a nombre de quién está: si es tuya va a «Mías»; si no, a «Otras personas».
              </Text>
              <Text style={styles.label}>Nombre en tu Agenda (opcional)</Text>
              <TextInput value={localForm.label} onChangeText={label => setLocalForm({ ...localForm, label })}
                placeholder="Mamá, Mi Nequi…" placeholderTextColor={colors.textTertiary} style={styles.input} />
              {localForm.error ? <Text style={styles.errorText}>{localForm.error}</Text> : null}
              <PrimaryButton title="Verificar y guardar" loading={saving} onPress={() => { void submitLocal(); }} />
            </ScrollView>
          )}
        </KeyboardAvoidingView>
      </Modal>

      {/* ── Rename a local-send recipient (whose it is comes from its holder) ── */}
      <Sheet visible={!!editEntry} onClose={() => { if (!saving) setEditEntry(null); }} title="Editar cuenta"
        subtitle={editEntry?.entry.subtitle}>
        {editEntry ? (
          <>
            <Text style={styles.label}>Nombre en tu Agenda</Text>
            <TextInput value={editEntry.label} onChangeText={label => setEditEntry({ ...editEntry, label })}
              placeholder="Mamá, Mi Nequi…" placeholderTextColor={colors.textTertiary} style={styles.input} />
            <PrimaryButton title="Guardar" loading={saving} onPress={() => { void submitEdit(); }} />
          </>
        ) : null}
      </Sheet>

      {/* ── Venezuelan Pago Móvil ── */}
      <Modal visible={!!veForm} animationType="slide" presentationStyle="pageSheet"
        onRequestClose={() => { if (!saving) setVeForm(null); }}>
        <KeyboardAvoidingView style={styles.sheetPage} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.pageHeader}>
            <Text style={styles.pageTitle}>{veForm?.id ? 'Editar Pago Móvil' : 'Nuevo Pago Móvil'}</Text>
            <TouchableOpacity onPress={() => setVeForm(null)} disabled={saving} accessibilityRole="button"
              accessibilityLabel="Cerrar" hitSlop={HIT}>
              <Icon name="x" size={24} color={colors.text.primary} />
            </TouchableOpacity>
          </View>
          {veForm ? (
            <ScrollView contentContainerStyle={styles.pageContent} keyboardShouldPersistTaps="handled">
              <Text style={[styles.label, styles.firstLabel]}>¿De quién es?</Text>
              <Segment value={veForm.relationship} ownDisabled={!ownCedula}
                onChange={relationship => setVeForm({ ...veForm, relationship })} />
              {!ownCedula ? (
                <Text style={styles.fieldHelp}>
                  Para guardar una cuenta como tuya necesitamos tu cédula venezolana verificada.
                </Text>
              ) : null}
              {veForm.relationship === 'third_party' ? (
                <>
                  <Text style={styles.label}>Nombre de la persona</Text>
                  <TextInput value={veForm.holderName} onChangeText={holderName => setVeForm({ ...veForm, holderName })}
                    placeholder="María Pérez" placeholderTextColor={colors.textTertiary} style={styles.input} />
                </>
              ) : null}
              <Text style={styles.label}>Cédula</Text>
              {veForm.relationship === 'own' ? (
                <View style={[styles.input, styles.picker, styles.lockedInput]}>
                  <Text style={styles.lockedValue}>{ownCedula}</Text>
                  <Icon name="lock" size={16} color={colors.text.light} />
                </View>
              ) : (
                <TextInput value={veForm.cedula} onChangeText={cedula => setVeForm({ ...veForm, cedula })}
                  autoCapitalize="characters" placeholder="V12345678" placeholderTextColor={colors.textTertiary}
                  style={styles.input} />
              )}
              {veForm.relationship === 'own' ? (
                <Text style={styles.fieldHelp}>La de tu verificación de identidad.</Text>
              ) : null}
              <Text style={styles.label}>Teléfono del Pago Móvil</Text>
              <TextInput value={veForm.phone} onChangeText={phone => setVeForm({ ...veForm, phone })}
                keyboardType="phone-pad" placeholder="0414 1234567" placeholderTextColor={colors.textTertiary}
                style={styles.input} />
              <Text style={styles.label}>Banco</Text>
              <TouchableOpacity style={[styles.input, styles.picker]} accessibilityRole="button"
                onPress={() => { setBankPicker(true); if (!banks.length) void loadBanks(); }}>
                <Text style={veForm.bank ? styles.pickerValue : styles.pickerPlaceholder} numberOfLines={1}>
                  {veForm.bank ? veForm.bank.name : 'Elige el banco'}
                </Text>
                <Icon name="chevron-down" size={18} color={colors.text.secondary} />
              </TouchableOpacity>
              <Text style={styles.label}>Nombre en tu Agenda (opcional)</Text>
              <TextInput value={veForm.label} onChangeText={label => setVeForm({ ...veForm, label })}
                placeholder="Mamá, Mi Banesco…" placeholderTextColor={colors.textTertiary} style={styles.input} />
              {veError ? <Text style={styles.errorText}>{veError}</Text> : null}
              <PrimaryButton title="Guardar" loading={saving} onPress={() => { void submitVe(); }} />
            </ScrollView>
          ) : null}
        </KeyboardAvoidingView>
        <Modal visible={bankPicker} animationType="slide" presentationStyle="pageSheet"
          onRequestClose={() => setBankPicker(false)}>
          <View style={styles.sheetPage}>
            <View style={styles.pageHeader}>
              <Text style={styles.pageTitle}>Elige el banco</Text>
              <TouchableOpacity onPress={() => setBankPicker(false)} accessibilityRole="button" accessibilityLabel="Cerrar"
                hitSlop={HIT}>
                <Icon name="x" size={24} color={colors.text.primary} />
              </TouchableOpacity>
            </View>
            <FlatList
              data={banks}
              keyExtractor={item => item.code}
              initialNumToRender={20}
              maxToRenderPerBatch={10}
              windowSize={21}
              getItemLayout={(_, index) => ({ length: BANK_ROW, offset: BANK_ROW * index, index })}
              ListEmptyComponent={(
                <EmptyState icon="wifi-off" title="No pudimos cargar los bancos" actionLabel="Reintentar"
                  onAction={() => { void loadBanks(); }} />
              )}
              renderItem={({ item }) => (
                <TouchableOpacity style={styles.bankRow} accessibilityRole="button"
                  onPress={() => { if (veForm) setVeForm({ ...veForm, bank: item }); setBankPicker(false); }}>
                  <Text style={styles.pickerValue} numberOfLines={1}>{item.name}</Text>
                  {veForm?.bank?.code === item.code ? <Icon name="check" size={18} color={colors.primaryDark} /> : null}
                </TouchableOpacity>
              )}
            />
          </View>
        </Modal>
      </Modal>

      {/* ── Withdrawal accounts: the Mis cuentas form, here ── */}
      <Modal visible={!!bankModal} animationType="slide" presentationStyle="pageSheet"
        onRequestClose={() => setBankModal(null)}>
        {bankModal ? (
          <AddPayoutMethodModal
            isVisible
            onClose={() => setBankModal(null)}
            onSuccess={() => {
              const editing = !!bankModal.editing;
              setBankModal(null);
              setTab('own');
              setBanner({ variant: 'success', message: editing ? 'Cuenta actualizada' : 'Cuenta guardada en tu Agenda' });
              void load();
            }}
            accountId={activeAccount?.id || null}
            editingPayoutMethod={bankModal.editing}
            initialCountryCode={bankModal.countryCode || null}
            initialPaymentMethodId={bankModal.paymentMethodId || null}
            lockCountry={!!bankModal.countryCode}
            lockPaymentMethod={!!bankModal.paymentMethodId}
          />
        ) : null}
      </Modal>
    </View>
  );
}

// ── small building blocks ───────────────────────────────────────────────────

function Sheet({ visible, onClose, title, subtitle, children }: {
  visible: boolean; onClose: () => void; title: string; subtitle?: string; children: React.ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <TouchableOpacity style={StyleSheet.absoluteFill} activeOpacity={1} onPress={onClose}
          accessibilityRole="button" accessibilityLabel="Cerrar" />
        <View style={styles.sheet}>
          <View style={styles.grabber} />
          <View style={styles.sheetHeader}>
            <View style={styles.flex}>
              <Text style={styles.sheetTitle}>{title}</Text>
              {subtitle ? <Text style={styles.sheetSubtitle} numberOfLines={1}>{subtitle}</Text> : null}
            </View>
            <TouchableOpacity onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar" hitSlop={HIT}>
              <Icon name="x" size={22} color={colors.text.secondary} />
            </TouchableOpacity>
          </View>
          {children}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function SheetOption({ icon, title, subtitle, onPress, disabled }: {
  icon: string; title: string; subtitle: string; onPress: () => void; disabled?: boolean;
}) {
  return (
    <TouchableOpacity style={[styles.option, disabled && styles.disabled]} onPress={onPress} disabled={disabled}
      accessibilityRole="button">
      <View style={styles.optionIcon}><MCIcon name={icon} size={22} color={colors.primaryDark} /></View>
      <View style={styles.flex}>
        <Text style={styles.optionTitle}>{title}</Text>
        <Text style={styles.optionSubtitle}>{subtitle}</Text>
      </View>
      <Icon name="chevron-right" size={18} color={colors.text.light} />
    </TouchableOpacity>
  );
}

function Segment({ value, onChange, ownDisabled = false }: {
  value: AgendaRelationship; onChange: (v: AgendaRelationship) => void; ownDisabled?: boolean;
}) {
  return (
    <View style={styles.segment}>
      {(['own', 'third_party'] as AgendaRelationship[]).map(option => (
        <TouchableOpacity key={option} onPress={() => onChange(option)} accessibilityRole="button"
          disabled={option === 'own' && ownDisabled}
          accessibilityState={{ selected: value === option, disabled: option === 'own' && ownDisabled }}
          style={[styles.segmentItem, value === option && styles.segmentActive,
            option === 'own' && ownDisabled && styles.disabled]}>
          <Text style={[styles.segmentText, value === option && styles.segmentTextActive]}>
            {option === 'own' ? 'Es mía' : 'De otra persona'}
          </Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

function PrimaryButton({ title, loading, onPress }: { title: string; loading: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity style={[styles.primaryButton, loading && styles.disabled]} onPress={onPress} disabled={loading}
      accessibilityRole="button">
      {loading ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryButtonText}>{title}</Text>}
    </TouchableOpacity>
  );
}

const HIT = { top: 8, bottom: 8, left: 8, right: 8 };
const SHEET_FADE_MS = 450;
const PENDING_POLLS = 6;
const PENDING_POLL_MS = 2000;
const BANK_ROW = 56;
const shadow = Platform.select({
  ios: { shadowColor: colors.primaryDeep, shadowOffset: { width: 0, height: 3 }, shadowOpacity: 0.07, shadowRadius: 8 },
  android: { elevation: 3 },
});

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  loader: { marginTop: 40 },
  disabled: { opacity: 0.6 },

  // Brand field (same language as Mis cuentas)
  brandField: { backgroundColor: colors.heroField, overflow: 'hidden' },
  fieldInner: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 18 },
  fieldEyebrow: { fontSize: 11, fontWeight: '700', letterSpacing: 2, color: colors.primaryLight, marginBottom: 6 },
  fieldTitle: { fontSize: 22, fontWeight: '800', color: colors.white },
  fieldSubtitle: { fontSize: 13, lineHeight: 19, color: 'rgba(255, 255, 255, 0.85)', marginTop: 6 },
  addHeaderButton: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center', alignItems: 'center',
  },
  tabs: {
    flexDirection: 'row', marginTop: 16, backgroundColor: 'rgba(255,255,255,0.18)', borderRadius: 12, padding: 4,
  },
  tab: { flex: 1, paddingVertical: 9, borderRadius: 9, alignItems: 'center' },
  tabActive: { backgroundColor: colors.white },
  tabText: { fontSize: 14, fontWeight: '700', color: colors.white },
  tabTextActive: { color: colors.primaryDeep },

  listContent: { paddingTop: 8, paddingHorizontal: 16, paddingBottom: 32, flexGrow: 1 },
  countryHeader: {
    fontSize: 11, fontWeight: '700', letterSpacing: 1, color: colors.text.light, textTransform: 'uppercase',
    marginTop: 14, marginBottom: 8, marginLeft: 4,
  },
  recentsHeader: { marginTop: 10 },
  recentsHint: { fontSize: 12, color: colors.text.secondary, marginTop: -4, marginBottom: 8, marginLeft: 4 },

  // Cards (Mis cuentas grammar)
  card: {
    flexDirection: 'row', backgroundColor: colors.background, borderRadius: 14, marginBottom: 10, overflow: 'hidden',
    ...shadow,
  },
  cardDefault: { borderWidth: 1.5, borderColor: colors.primaryDark },
  cardIconChip: {
    width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center', alignSelf: 'center',
    marginLeft: 12,
  },
  cardInner: { flex: 1, paddingVertical: 14, paddingHorizontal: 12 },
  cardRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  cardFlag: { marginRight: 6 },
  cardTitle: { flex: 1, fontSize: 14, fontWeight: '700', color: colors.text.primary },
  cardActions: { flexDirection: 'row', alignItems: 'center', marginLeft: 8 },
  actionBtn: { paddingHorizontal: 6, paddingVertical: 4 },
  cardRow2: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  typePill: { paddingHorizontal: 6, paddingVertical: 1, borderRadius: 5, marginRight: 5 },
  typePillText: { fontSize: 10, fontWeight: '700' },
  defaultBadge: { backgroundColor: colors.primaryLight, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 5 },
  defaultText: { fontSize: 10, color: colors.primaryDeep, fontWeight: '700' },
  cardDetail: { fontSize: 12, color: colors.text.secondary },
  sendChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', marginTop: 10,
    backgroundColor: colors.primaryDark, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6,
  },
  sendChipText: { fontSize: 13, fontWeight: '700', color: colors.white },
  recentCard: { alignItems: 'center', paddingRight: 12 },
  recentFlag: { marginLeft: 14 },
  saveChip: {
    flexDirection: 'row', alignItems: 'center', gap: 5, borderWidth: 1, borderColor: colors.primaryDark,
    borderRadius: 16, paddingHorizontal: 10, paddingVertical: 5,
  },
  saveChipText: { fontSize: 12, fontWeight: '700', color: colors.primaryDark },
  addMoreButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 16, marginTop: 6,
    borderRadius: 14, borderWidth: 1.5, borderStyle: 'dashed', borderColor: colors.primaryLight,
  },
  addMoreText: { fontSize: 14, fontWeight: '700', color: colors.primary },

  // Bottom sheet
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(6, 78, 59, 0.35)' },
  sheet: {
    backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: 20, paddingBottom: 34, paddingTop: 8,
  },
  grabber: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.neutralDark, marginBottom: 12 },
  sheetHeader: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14 },
  sheetTitle: { fontSize: 18, fontWeight: '800', color: colors.text.primary },
  sheetSubtitle: { fontSize: 13, color: colors.text.secondary, marginTop: 3 },
  sheetNote: { fontSize: 12, lineHeight: 18, color: colors.text.secondary, marginTop: 6 },
  option: {
    flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 14, marginBottom: 10,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.neutralDark,
  },
  optionIcon: {
    width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  optionTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  optionSubtitle: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  ownership: { fontSize: 11, fontWeight: '700', color: colors.text.light, marginTop: 4 },
  ownershipOpen: { color: colors.primaryDark },
  stepHint: { fontSize: 14, fontWeight: '600', color: colors.text.secondary, marginBottom: 12, paddingHorizontal: 20 },
  countryRow: {
    flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, height: 56,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  backButton: { marginRight: 8 },
  stepHintFlush: { paddingHorizontal: 0 },
  lockedInput: { backgroundColor: colors.neutralDark },
  lockedValue: { fontSize: 16, fontWeight: '600', color: colors.text.secondary },
  fieldHelp: { fontSize: 12, color: colors.text.secondary, marginTop: 6 },

  // Forms
  sheetPage: { flex: 1, backgroundColor: colors.background },
  pageHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20,
    paddingTop: 20, paddingBottom: 12,
  },
  pageTitle: { fontSize: 20, fontWeight: '800', color: colors.text.primary },
  pageContent: { paddingHorizontal: 20, paddingBottom: 40 },
  label: { fontSize: 13, fontWeight: '600', color: colors.text.secondary, marginTop: 16, marginBottom: 6 },
  firstLabel: { marginTop: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, minHeight: 48,
    fontSize: 16, color: colors.text.primary, backgroundColor: colors.background,
  },
  picker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  pickerValue: { fontSize: 16, fontWeight: '600', color: colors.text.primary, flexShrink: 1 },
  pickerPlaceholder: { fontSize: 16, color: colors.textTertiary },
  errorText: { fontSize: 13, color: colors.error.text, marginTop: 12 },
  segment: { flexDirection: 'row', gap: 8 },
  segmentItem: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 10, alignItems: 'center',
  },
  segmentActive: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  segmentText: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  segmentTextActive: { color: colors.primaryDeep },
  primaryButton: {
    marginTop: 22, minHeight: 52, borderRadius: 14, backgroundColor: colors.primaryDark,
    alignItems: 'center', justifyContent: 'center',
  },
  primaryButtonText: { fontSize: 16, fontWeight: '700', color: colors.white },
  bankRow: {
    height: BANK_ROW, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
});
