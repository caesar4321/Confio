// A purchase the assistant is making, drawn in the chat and updated in place:
// the products to pick from (with their photos), the store's sign-in, a code
// the store sent, and the order to approve. The person never goes to the
// store: everything they are asked is asked here.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import QRCode from 'react-native-qrcode-svg';
import Share from 'react-native-share';
import ViewShot from 'react-native-view-shot';

import { Text, TextInput } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { colors } from '../config/theme';
import { saveImageToGallery } from '../utils/saveImageToGallery';
import {
  ACTIVE, APPROVE_AGENT_ORDER, AgentAnswer, AgentOption, AgentTask, CANCEL_AGENT_TASK, CHOOSE_AGENT_OPTION,
  GET_AGENT_TASK, GIVE_AGENT_CODE, SIGN_IN_AGENT_STORE,
} from './api';

const POLL_MS = 2500;
// A tap whose answer never comes stops holding the card after this; the next refresh shows what it did.
const TAP_DEADLINE_MS = 30_000;

const https = (uri: string) => (/^https:\/\//.test(uri) ? uri : '');

function Photo({ uri, size }: { uri: string; size: number }) {
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size };
  if (!https(uri) || failed) {
    return <View style={[styles.photo, styles.photoEmpty, box]}><Icon name="package" size={size / 3} color="#9CA3AF" /></View>;
  }
  return <Image source={{ uri }} style={[styles.photo, box]} resizeMode="contain" onError={() => setFailed(true)} />;
}

export function PurchaseCard({ taskId, onStores, onOpen }: {
  taskId: string; onStores?: () => void; onOpen?: (screen: string, params?: Record<string, unknown>) => void;
}) {
  const client = useApolloClient();
  const [task, setTask] = useState<AgentTask | null | undefined>(undefined);
  const [note, setNote] = useState<string | null>(null);
  const [tapping, setTapping] = useState<string | null>(null);
  // Each answered tap starts a new epoch: a refresh that left before it is dropped.
  const epoch = useRef(0);
  const busy = useRef(false);
  const alive = useRef(true);
  const pending = useRef<number | null>(null);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    if (!alive.current) {
      return;
    }
    const mine = epoch.current;
    pending.current = mine;
    try {
      const result = await client.query({
        query: GET_AGENT_TASK, variables: { id: taskId }, fetchPolicy: 'no-cache',
        context: { queryDeduplication: false },
      });
      if (alive.current && epoch.current === mine && !busy.current) {
        setTask(result.data?.agentTask ?? null);
      }
    } catch {
      // The next refresh tries again.
    } finally {
      if (pending.current === mine) {
        pending.current = null;
      }
    }
  }, [client, taskId]);
  useEffect(() => { load(); }, [load]);
  const polling = task === undefined || (!!task && ACTIVE.has(task.status));
  useEffect(() => {
    if (!polling) {
      return undefined;
    }
    const timer = setInterval(() => {
      if (pending.current !== epoch.current) {
        load();
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, load]);

  const act = async (which: string, mutation: any, variables: Record<string, unknown>, field: string) => {
    if (busy.current) {
      return false;
    }
    busy.current = true;
    setTapping(which);
    setNote(null);
    let expired = false;
    const deadline = setTimeout(() => {
      if (!alive.current) {
        return;
      }
      expired = true;
      epoch.current += 1;
      busy.current = false;
      setTapping(null);
      load();
    }, TAP_DEADLINE_MS);
    let ok = false;
    try {
      const result = await client.mutate({ mutation, variables: { id: taskId, ...variables }, fetchPolicy: 'no-cache' });
      const answer: AgentAnswer | undefined = result.data?.[field];
      ok = !!answer?.success;
      if (alive.current && !expired) {
        epoch.current += 1;
        if (answer?.task) {
          setTask(answer.task);
        }
        if (!ok) {
          setNote(answer?.errors?.[0] || 'No pude hacerlo. Inténtalo de nuevo.');
        }
      }
    } catch {
      if (alive.current && !expired) {
        epoch.current += 1;
        setNote('No pude hacerlo. Revisa tu conexión.');
      }
    } finally {
      clearTimeout(deadline);
      if (alive.current && !expired) {
        busy.current = false;
        setTapping(null);
        load();
      }
    }
    return ok;
  };

  const cancel = () => Alert.alert('Cancelar la compra', 'El asistente dejará esta compra.', [
    { text: 'Volver', style: 'cancel' },
    { text: 'Cancelar la compra', style: 'destructive',
      onPress: () => { act('cancel', CANCEL_AGENT_TASK, {}, 'cancelAgentTask'); } },
  ]);

  if (task === undefined) {
    return <View style={styles.card}><ActivityIndicator color={colors.primaryDark} /></View>;
  }
  if (task === null) {
    return null;   // another account's, or gone: nothing to draw
  }
  const waiting = task.status === 'needs_person';
  const working = ACTIVE.has(task.status) && !waiting;
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        {working ? <ActivityIndicator size="small" color={colors.primaryDark} /> : (
          <Icon name={task.status === 'payment_ready' ? 'check-circle' : waiting ? 'shopping-bag' : 'info'} size={18}
            color={colors.primaryDark} />
        )}
        <Text style={styles.site} numberOfLines={1}>{task.site}</Text>
      </View>
      {/* The server's words: they name the right way to pay for the store's country. */}
      <Text style={styles.message}>{task.message}</Text>
      {waiting && task.reason === 'choose' ? (
        <Products options={task.options} picking={tapping}
          onPick={(index) => act(`pick:${index}`, CHOOSE_AGENT_OPTION, { index }, 'chooseAgentOption')} />
      ) : null}
      {waiting && task.reason === 'login' ? (
        <SignIn site={task.site} sending={tapping === 'signin'}
          onSend={(identifier, password) => act('signin', SIGN_IN_AGENT_STORE, { identifier, password },
            'signInAgentStore')} />
      ) : null}
      {waiting && task.reason === 'otp' ? (
        <Code sending={tapping === 'code'} onSend={(code) => act('code', GIVE_AGENT_CODE, { code }, 'giveAgentCode')} />
      ) : null}
      {waiting && task.reason === 'approve' && task.order ? (
        <View style={styles.order}>
          <Photo uri={task.order.image} size={72} />
          <View style={styles.orderText}>
            <Text style={styles.title} numberOfLines={3}>{task.order.item}</Text>
            <Text style={styles.total}>{task.order.total}</Text>
            {task.order.address ? (
              <Text style={styles.address} numberOfLines={2}>Envío a: {task.order.address}</Text>
            ) : null}
          </View>
        </View>
      ) : null}
      {waiting && task.reason === 'approve' && task.order ? (
        <Button title="Confirmar pedido" loading={tapping === 'approve'}
          onPress={() => { act('approve', APPROVE_AGENT_ORDER, { total: task.order!.total }, 'approveAgentOrder'); }} />
      ) : null}
      {task.status === 'payment_ready' && task.payQr ? <StoreQr code={task.payQr} total={task.order?.total ?? ''} /> : null}
      {task.status === 'payment_ready' && task.payDetails?.length ? <PayDetails details={task.payDetails} /> : null}
      {task.status === 'payment_ready' && task.openAccountMethod && onOpen ? (
        <Button title="Abrir mi cuenta local" variant="secondary"
          onPress={() => onOpen('LocalAccountApplication', { methodId: task.openAccountMethod })} />
      ) : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
      {ACTIVE.has(task.status) ? (
        <Pressable onPress={cancel} accessibilityRole="button" style={styles.link} disabled={tapping !== null}>
          <Text style={styles.linkText}>Cancelar la compra</Text>
        </Pressable>
      ) : onStores ? (
        <Pressable onPress={onStores} accessibilityRole="button" style={styles.link}>
          <Text style={styles.linkText}>Tiendas con tu sesión</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// What the store's order page says to pay it with, each line copied with a tap.
function PayDetails({ details }: { details: { label: string; value: string }[] }) {
  const [copied, setCopied] = useState<string | null>(null);
  return (
    <View style={styles.details}>
      {details.map((item) => (
        <Pressable key={item.label} accessibilityRole="button" accessibilityLabel={`Copiar ${item.label}`}
          style={styles.detail} onPress={() => { Clipboard.setString(item.value); setCopied(item.label); }}>
          <View style={styles.detailText}>
            <Text style={styles.detailLabel}>{item.label}</Text>
            <Text style={styles.detailValue} selectable>{item.value}</Text>
          </View>
          <Icon name={copied === item.label ? 'check' : 'copy'} size={16} color={colors.primaryDark} />
        </Pressable>
      ))}
    </View>
  );
}

// The store's own QR, for the person's bank app: saved to the gallery or shared, then uploaded there.
function StoreQr({ code, total }: { code: string; total: string }) {
  const shot = useRef<ViewShot>(null);
  const [said, setSaid] = useState<string | null>(null);
  const capture = async () => {
    try {
      return (await shot.current?.capture?.()) || null;
    } catch {
      return null;
    }
  };
  const save = async () => {
    const uri = await capture();
    if (!uri) return;
    try {
      await saveImageToGallery(uri);
      setSaid('QR guardado en tu galería. Súbelo en la app de tu banco.');
    } catch {
      setSaid('No pude guardar la imagen. Revisa el permiso de la galería.');
    }
  };
  const share = async () => {
    const uri = await capture();
    if (!uri) return;
    try {
      await Share.open({ url: uri, type: 'image/jpeg', title: 'QR del pedido' });
    } catch {
      // closed by the person
    }
  };
  return (
    <View style={styles.qrBox}>
      <ViewShot ref={shot} options={{ format: 'jpg', quality: 0.95 }}>
        <View style={styles.qrInner}>
          <QRCode value={code} size={200} backgroundColor="#FFFFFF" />
          {total ? <Text style={styles.total}>{total}</Text> : null}
        </View>
      </ViewShot>
      <View style={styles.qrActions}>
        <Button title="Guardar QR" onPress={save} />
        <Pressable onPress={share} accessibilityRole="button" style={styles.link}>
          <Text style={styles.linkText}>Compartir</Text>
        </Pressable>
      </View>
      {said ? <Text style={styles.note}>{said}</Text> : null}
    </View>
  );
}

function Products({ options, picking, onPick }: {
  options: AgentOption[]; picking: string | null; onPick: (index: number) => void;
}) {
  return (
    <FlatList
      horizontal
      data={options}
      keyExtractor={(_, index) => String(index)}
      showsHorizontalScrollIndicator={false}
      initialNumToRender={5}
      maxToRenderPerBatch={5}
      windowSize={5}
      contentContainerStyle={styles.products}
      renderItem={({ item, index }) => (
        <Pressable style={styles.product} disabled={picking !== null} onPress={() => onPick(index)}
          accessibilityRole="button" accessibilityLabel={`Elegir ${item.title}${item.price ? `, ${item.price}` : ''}`}>
          <Photo uri={item.image} size={132} />
          <Text style={styles.title} numberOfLines={3}>{item.title}</Text>
          {item.price ? <Text style={styles.price}>{item.price}</Text> : null}
          <View style={styles.pick}>
            {picking === `pick:${index}` ? <ActivityIndicator size="small" color="#FFFFFF" />
              : <Text style={styles.pickText}>Elegir</Text>}
          </View>
        </Pressable>
      )}
    />
  );
}

function SignIn({ site, sending, onSend }: {
  site: string; sending: boolean; onSend: (identifier: string, password: string) => Promise<boolean>;
}) {
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const send = async () => {
    if (await onSend(identifier.trim(), password)) {
      setPassword('');   // never kept on the phone once it is sent
    }
  };
  return (
    <View style={styles.form}>
      <TextInput style={styles.input} value={identifier} onChangeText={setIdentifier} autoCapitalize="none"
        autoCorrect={false} keyboardType="email-address" placeholder={`Correo o usuario de ${site}`}
        placeholderTextColor="#9CA3AF" accessibilityLabel="Correo o usuario de la tienda" />
      <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none"
        autoCorrect={false} placeholder="Contraseña de la tienda" placeholderTextColor="#9CA3AF"
        accessibilityLabel="Contraseña de la tienda" />
      <Button title="Entrar" onPress={send} loading={sending} disabled={!identifier.trim() || !password} />
    </View>
  );
}

function Code({ sending, onSend }: { sending: boolean; onSend: (code: string) => Promise<boolean> }) {
  const [code, setCode] = useState('');
  return (
    <View style={styles.form}>
      <TextInput style={styles.input} value={code} onChangeText={setCode} keyboardType="number-pad"
        autoComplete="one-time-code" placeholder="Código de verificación" placeholderTextColor="#9CA3AF"
        accessibilityLabel="Código de verificación" />
      <Button title="Enviar código" onPress={async () => { if (await onSend(code)) setCode(''); }} loading={sending}
        disabled={code.trim().length < 3} />
    </View>
  );
}

const styles = StyleSheet.create({
  qrBox: { marginTop: 12, alignItems: 'center' },
  address: { fontSize: 13, color: '#6B7280', marginTop: 4 },
  details: { marginTop: 12, borderRadius: 12, backgroundColor: '#F9FAFB', paddingHorizontal: 12 },
  detail: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E5E7EB' },
  detailText: { flex: 1, marginRight: 8 },
  detailLabel: { fontSize: 12, color: '#6B7280' },
  detailValue: { fontSize: 15, color: '#111827', marginTop: 2 },
  qrInner: { alignItems: 'center', padding: 16, backgroundColor: '#FFFFFF', borderRadius: 12 },
  qrActions: { marginTop: 12, alignSelf: 'stretch', gap: 4 },
  card: {
    marginTop: 8, padding: 12, borderRadius: 16, borderWidth: 1, borderColor: '#D1FAE5',
    backgroundColor: colors.background, gap: 10,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  site: { flex: 1, fontSize: 13, color: colors.text.secondary },
  message: { fontSize: 15, lineHeight: 21, color: colors.text.primary },
  products: { gap: 10, paddingVertical: 2 },
  product: {
    width: 156, padding: 10, borderRadius: 14, borderWidth: 1, borderColor: '#E5E7EB',
    backgroundColor: colors.background, gap: 6,
  },
  photo: { borderRadius: 10, backgroundColor: '#FFFFFF', alignSelf: 'center' },
  photoEmpty: { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.neutralDark },
  title: { fontSize: 14, lineHeight: 19, color: colors.text.primary },
  price: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  pick: {
    minHeight: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryDark, marginTop: 2,
  },
  pickText: { fontSize: 15, fontWeight: '600', color: '#FFFFFF' },
  form: { gap: 8 },
  input: {
    minHeight: 48, borderRadius: 12, borderWidth: 1, borderColor: '#D1D5DB', paddingHorizontal: 12,
    fontSize: 16, color: colors.text.primary, backgroundColor: colors.background,
  },
  order: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  orderText: { flex: 1, gap: 4 },
  total: { fontSize: 18, fontWeight: '700', color: colors.text.primary },
  note: { fontSize: 14, color: colors.error.text },
  link: { alignSelf: 'center', minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  linkText: { fontSize: 14, color: colors.text.secondary, textDecorationLine: 'underline' },
});
