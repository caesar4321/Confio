// A purchase the assistant is making, drawn in the chat and updated in place:
// the products to pick from (with their photos), the store's sign-in, a code
// the store sent, and the order to approve. The person never goes to the
// store: everything they are asked is asked here.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, View } from 'react-native';
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
import { PurchaseDone } from './PurchaseDone';
import { PurchaseJourney } from './PurchaseJourney';
import { drawable, Photo, TaskCard } from './TaskCard';
import {
  ACTIVE, ADD_AGENT_ADDRESS, AgentCard, AgentNewAddress, ANSWER_AGENT_CARD, ANSWER_AGENT_NOTIFY, ANSWER_AGENT_REQUEST, ANSWER_AGENT_STEP, APPROVE_AGENT_ORDER, AgentAnswer, AgentOption, AgentOrder, AgentTask,
  CANCEL_AGENT_TASK, CHANGE_AGENT_ADDRESS, CHOOSE_AGENT_ADDRESS, CHOOSE_AGENT_OPTIONS, GET_AGENT_TASK, GET_AGENT_TASK_CARD, GIVE_AGENT_CODE, RESUME_AGENT_PAYMENT, SIGN_IN_AGENT_STORE,
} from './api';
import { CapRule, cartTop } from './helpers';

const POLL_MS = 2500;
// A tap whose answer never comes stops holding the card after this; the next refresh shows what it did.
const TAP_DEADLINE_MS = 30_000;

// What the person approves is the order on the card: its total and where it is delivered.
const approval = (order: AgentOrder) => ({ total: order.total, address: order.address || '' });

export function PurchaseCard({ taskId, onStores, onOpen }: {
  taskId: string; onStores?: () => void; onOpen?: (screen: string, params?: Record<string, unknown>) => void;
}) {
  const client = useApolloClient();
  const [task, setTask] = useState<AgentTask | null | undefined>(undefined);
  // The general card the server composed for this task as it is now (TaskCard), or null: the older drawing.
  const [card, setCard] = useState<AgentCard | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [tapping, setTapping] = useState<string | null>(null);
  // Each answered tap starts a new epoch: a refresh that left before it is dropped.
  const epoch = useRef(0);
  const busy = useRef(false);
  const alive = useRef(true);
  const pending = useRef<number | null>(null);
  // The last status this card drew, and whether it saw the order become done.
  const watched = useRef<string | null>(null);
  const celebrate = useRef(false);
  useEffect(() => () => { alive.current = false; }, []);

  // Asked only when the task waits for the person or stopped; its own query, so a server without it (or a
  // failure) leaves the older drawing.
  const cardFor = useCallback(async (shown: AgentTask | null | undefined): Promise<AgentCard | null> => {
    if (!shown || !(shown.status === 'needs_person' || shown.status === 'stopped')) {
      return null;
    }
    try {
      const result = await client.query({
        query: GET_AGENT_TASK_CARD, variables: { id: taskId }, fetchPolicy: 'no-cache',
        context: { queryDeduplication: false },
      });
      const found: AgentCard | null = result.data?.agentTaskCard ?? null;
      return drawable(found) ? found : null;
    } catch {
      return null;
    }
  }, [client, taskId]);

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
      const shown: AgentTask | null = result.data?.agentTask ?? null;
      const general = await cardFor(shown);
      // The task and its card are drawn together, from the same refresh.
      if (alive.current && epoch.current === mine && !busy.current) {
        setTask(shown);
        setCard(general);
      }
    } catch {
      // The next refresh tries again.
    } finally {
      if (pending.current === mine) {
        pending.current = null;
      }
    }
  }, [client, taskId, cardFor]);
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
      const general = answer?.task ? await cardFor(answer.task) : null;
      if (alive.current && !expired) {
        epoch.current += 1;
        if (answer?.task) {
          setTask(answer.task);
          setCard(general);
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
  const done = task.status === 'payment_ready';
  // An order already placed (its state, a cancellation, a return): no purchase journey.
  const managing = task.kind === 'manage';
  const answered = managing && task.status === 'stopped' && task.reason === 'answered';
  // A general card replaces the older drawing of the questions it composes (an order, a request, a step,
  // Sí, avísame); the native ones (products, sign-in, a code, an address, the account wait, paying) stay.
  // Asked apart from the task, so it may be a moment newer or older: drawn only when it is this task's state.
  const shownCard = card && card.status === task.status && card.reason === task.reason ? card : null;
  const legacy = shownCard === null;
  // The order became done while this card was watching: its moment plays once. A card that
  // opens on an order already done (an old message scrolled back) shows it quietly.
  if (task.status !== watched.current) {
    if (done && watched.current !== null && ACTIVE.has(watched.current)) {
      celebrate.current = true;
    }
    watched.current = task.status;
  }
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Icon name={answered ? 'check-circle' : managing ? 'package' : ACTIVE.has(task.status) || done ? 'shopping-bag'
          : 'info'} size={18} color={colors.primaryDark} />
        <Text style={styles.site} numberOfLines={1}>{task.site}</Text>
      </View>
      {done ? <PurchaseDone celebrate={celebrate.current} /> : null}
      {/* Where the purchase is: alive while the assistant works, still when it is the person's turn. */}
      {managing ? (
        working ? <ActivityIndicator color={colors.primaryDark} style={styles.managing} /> : null
      ) : (
        <PurchaseJourney stage={done ? 'done' : task.stage} working={working} site={task.site}
          stopped={!ACTIVE.has(task.status) && !done} />
      )}
      {/* The server's words: they name the right way to pay for the store's country. */}
      <Text style={styles.message}>{task.message}</Text>
      {waiting && task.reason === 'choose' ? (
        <Products options={task.options} rule={task.capRule} picking={tapping}
          onBuy={(items, cap) => act('pick', CHOOSE_AGENT_OPTIONS,
            // The top total the button showed goes back with the tap: only then does it approve up to it.
            { items, cap }, 'chooseAgentOptions')} />
      ) : null}
      {waiting && task.reason === 'login' ? (
        <SignIn site={task.site} sending={tapping === 'signin'}
          onSend={(identifier, password) => act('signin', SIGN_IN_AGENT_STORE, { identifier, password },
            'signInAgentStore')} />
      ) : null}
      {waiting && task.reason === 'otp' ? (
        <Code sending={tapping === 'code'} onSend={(code) => act('code', GIVE_AGENT_CODE, { code }, 'giveAgentCode')} />
      ) : null}
      {shownCard ? (
        <TaskCard card={shownCard} tapping={tapping} onOpen={onOpen}
          onAnswer={(one) => { act(`card:${one.id}`, ANSWER_AGENT_CARD, { action: one.id, binding: shownCard.binding },
            'answerAgentCard'); }} />
      ) : null}
      {legacy && waiting && (task.reason === 'approve' || task.reason === 'subscribe') && task.order ? (
        <View style={styles.order}>
          <Photo uri={task.order.image} size={72} />
          <View style={styles.orderText}>
            <OrderItems order={task.order} />
            {(task.order.breakdown ?? []).map((line) => (
              <View key={line.label} style={styles.line}>
                <Text style={styles.lineLabel}>{line.label}</Text>
                <Text style={styles.lineValue}>{line.value}</Text>
              </View>
            ))}
            <Text style={styles.total}>{task.order.breakdown?.length ? `Total ${task.order.total}` : task.order.total}</Text>
            {task.order.address ? (
              <Text style={styles.address}>Envío a: {task.order.address}</Text>
            ) : null}
            {task.reason === 'approve' && task.order.address ? (
              <Pressable onPress={() => act('address', CHANGE_AGENT_ADDRESS, {}, 'changeAgentAddress')}
                accessibilityRole="button" accessibilityLabel="Cambiar dirección" style={styles.changeAddress}
                disabled={tapping !== null}>
                {tapping === 'address' ? <ActivityIndicator color={colors.primaryDark} />
                  : <Text style={styles.linkText}>Cambiar dirección</Text>}
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}
      {legacy && waiting && task.reason === 'act' && task.request ? (
        <View style={styles.request}>
          <Icon name="alert-circle" size={16} color={colors.onHeroField} />
          <View style={styles.requestBody}>
            <Text style={styles.requestText}>{task.request}</Text>
            {task.requestButton ? (
              <Text style={styles.requestButton}>Botón de {task.site}: «{task.requestButton}»</Text>
            ) : null}
          </View>
        </View>
      ) : null}
      {legacy && waiting && task.reason === 'act' ? (
        <View style={styles.stepRow}>
          <Button title="Sí, envíala" loading={tapping === 'act:yes'}
            onPress={() => act('act:yes', ANSWER_AGENT_REQUEST, { yes: true, what: task.request }, 'answerAgentRequest')} />
          <Pressable onPress={() => act('act:no', ANSWER_AGENT_REQUEST, { yes: false, what: task.request },
            'answerAgentRequest')}
            accessibilityRole="button" style={styles.link} disabled={tapping !== null}>
            <Text style={styles.linkText}>No, déjalo así</Text>
          </Pressable>
        </View>
      ) : null}
      {/* Found and picked, but this country's stores cannot be paid yet: the intent probe for paying them. */}
      {legacy && task.status === 'stopped' && (task.reason === 'no_rail' || task.reason === 'payer_data') ? (
        task.notify === 'yes' ? (
          <Text style={styles.message}>¡Anotado! Te aviso apenas pueda pagar {task.reason === 'payer_data' ? 'esta tienda' : 'tiendas de aquí'}.</Text>
        ) : task.notify === 'no' ? null : (
          <View>
            <Text style={styles.message}>¿Te aviso cuando pueda pagar {task.reason === 'payer_data' ? 'esta tienda' : 'tiendas de aquí'}?</Text>
            <View style={styles.stepRow}>
              <Button title="Sí, avísame" loading={tapping === 'notify:yes'}
                onPress={() => act('notify:yes', ANSWER_AGENT_NOTIFY, { yes: true }, 'answerAgentNotify')} />
              <Pressable onPress={() => act('notify:no', ANSWER_AGENT_NOTIFY, { yes: false }, 'answerAgentNotify')}
                accessibilityRole="button" style={styles.link} disabled={tapping !== null}>
                <Text style={styles.linkText}>Solo miraba</Text>
              </Pressable>
            </View>
          </View>
        )
      ) : null}
      {waiting && task.reason === 'address' ? (
        <View style={styles.addresses}>
          {(task.order?.addresses ?? []).map((address, index) => (
            <Pressable key={`${index}:${address}`} accessibilityRole="button" accessibilityLabel={address}
              style={styles.addressOption}
              disabled={tapping !== null}
              onPress={() => act(`address:${index}`, CHOOSE_AGENT_ADDRESS, { index, address }, 'chooseAgentAddress')}>
              <Icon name="map-pin" size={16} color={colors.primaryDark} />
              <Text style={styles.addressText}>{address}</Text>
              {tapping === `address:${index}` ? <ActivityIndicator color={colors.primaryDark} /> : null}
            </Pressable>
          ))}
          <NewAddress key={task.id} draft={task.order?.draftAddress ?? null} open={!task.order?.addresses?.length}
            sending={tapping === 'new_address'} disabled={tapping !== null}
            onSend={(address) => act('new_address', ADD_AGENT_ADDRESS, { address }, 'addAgentAddress')} />
        </View>
      ) : null}
      {legacy && waiting && task.reason === 'step' ? (
        <View style={styles.stepRow}>
          <Button title="Sí, hazlo" loading={tapping === 'step:yes'}
            onPress={() => act('step:yes', ANSWER_AGENT_STEP, { yes: true }, 'answerAgentStep')} />
          <Pressable onPress={() => act('step:no', ANSWER_AGENT_STEP, { yes: false }, 'answerAgentStep')}
            accessibilityRole="button" style={styles.link} disabled={tapping !== null}>
            <Text style={styles.linkText}>No</Text>
          </Pressable>
        </View>
      ) : null}
      {legacy && waiting && task.reason === 'approve' && task.order ? (
        <Button title="Confirmar pedido" loading={tapping === 'approve'}
          onPress={() => { act('approve', APPROVE_AGENT_ORDER, approval(task.order!), 'approveAgentOrder'); }} />
      ) : null}
      {/* Buying and paying is Cuenta inteligente's (spec decision 37): the offer instead of a confirm. Back
          subscribed, "seguir" resumes and the ordinary order card follows (who pays, the balance). */}
      {legacy && waiting && task.reason === 'subscribe' && task.order ? (
        <View style={styles.stepRow}>
          {onOpen ? (
            <Button title="Activar Cuenta inteligente"
              onPress={() => onOpen('SmartAccountOffer', { door: 'chip', trigger: 'agent_purchase' })} />
          ) : null}
          <Pressable accessibilityRole="button" accessibilityLabel="Ya la activé: seguir" style={styles.link}
            disabled={tapping !== null}
            onPress={() => { act('approve', APPROVE_AGENT_ORDER, approval(task.order!), 'approveAgentOrder'); }}>
            <Text style={styles.linkText}>Ya la activé: seguir</Text>
          </Pressable>
        </View>
      ) : null}
      {/* Paid by the Cuenta inteligente, never by the personal wallet: the one action that lets it pay, then
          "Ya lo hice: pagar". Loaded only for this card (its signing flow is the Cuenta inteligente one). */}
      {waiting && task.reason === 'account_wait' ? (() => {
        const { AccountWait } = require('./AccountWait');
        return <AccountWait taskId={taskId} resuming={tapping === 'resume'} onOpen={onOpen}
          onResume={() => act('resume', RESUME_AGENT_PAYMENT, {}, 'resumeAgentPayment')} />;
      })() : null}
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

// Every product the order holds, with how many: what the person approves.
function OrderItems({ order }: { order: AgentOrder }) {
  const items = order.items ?? [];
  if (items.length === 0 || (items.length === 1 && items[0].quantity === 1)) {
    return <Text style={styles.title} numberOfLines={3}>{items[0]?.title || order.item}</Text>;
  }
  return (
    <>
      {items.map((one, index) => (
        <Text key={`${index}:${one.title}`} style={styles.title} numberOfLines={2}>{`${one.quantity} × ${one.title}`}</Text>
      ))}
    </>
  );
}

type Pick = { index: number; quantity: number };

// The products found: one or more are chosen, each with a quantity, then confirmed with one tap. The button
// says the most the whole cart may cost (spec decision 42) before it is tapped; tapping it approves up to that.
function Products({ options, rule, picking, onBuy }: {
  options: AgentOption[]; rule?: CapRule | null; picking: string | null;
  onBuy: (items: Pick[], cap: string | null) => Promise<boolean>;
}) {
  const [chosen, setChosen] = useState<Record<number, number>>({});
  const most = rule?.maxQuantity || 9;
  const items: Pick[] = Object.keys(chosen).map(Number).sort((a, b) => a - b)
    .map((index) => ({ index, quantity: chosen[index] }));
  const units = items.reduce((sum, one) => sum + one.quantity, 0);
  const picks = items.map((one) => ({ price: options[one.index]?.price ?? '', unit: options[one.index]?.unit,
    quantity: one.quantity }));
  // One unit of one product: its own top total, also from a server that sends no rule.
  const top = cartTop(picks, rule)
    ?? (items.length === 1 && items[0].quantity === 1 ? options[items[0].index]?.cap ?? null : null);
  const toggle = (index: number) => setChosen((now) => {
    const next = { ...now };
    if (next[index]) {
      delete next[index];
    } else {
      next[index] = 1;
    }
    return next;
  });
  const step = (index: number, by: number) => setChosen((now) => (
    now[index] ? { ...now, [index]: Math.min(most, Math.max(1, now[index] + by)) } : now));
  const busy = picking !== null;
  return (
    <View style={styles.choose}>
      <FlatList
        horizontal
        data={options}
        extraData={chosen}
        keyExtractor={(_, index) => String(index)}
        showsHorizontalScrollIndicator={false}
        initialNumToRender={5}
        maxToRenderPerBatch={5}
        windowSize={5}
        contentContainerStyle={styles.products}
        renderItem={({ item, index }) => {
          const quantity = chosen[index] ?? 0;
          return (
            // The stepper is a sibling of the toggle, never inside it: a tap at a limit must not fall through
            // to the toggle (which removed the product), and VoiceOver reaches each control.
            <View style={[styles.product, quantity ? styles.productChosen : null]}>
              <Pressable disabled={busy} onPress={() => toggle(index)} accessibilityRole="checkbox"
                accessibilityState={{ checked: !!quantity, disabled: busy }}
                accessibilityLabel={`${quantity ? 'Quitar' : 'Elegir'} ${item.title}${item.price ? `, ${item.price}` : ''}${item.cap ? `, hasta ${item.cap} con envío` : ''}`}>
                <Photo uri={item.image} size={132} />
                <Text style={styles.title} numberOfLines={3}>{item.title}</Text>
                {item.price ? <Text style={styles.price}>{item.price}</Text> : null}
                {item.rating ? (
                  <Text style={styles.rating} accessibilityLabel={`${item.rating} de 5 estrellas${item.reviews ? `, ${item.reviews} opiniones` : ''}`}>
                    ★ {item.rating}{item.reviews ? ` (${item.reviews})` : ''}
                  </Text>
                ) : null}
                {/* One unit's top total, said before any tap. */}
                {item.cap ? <Text style={styles.cap}>Hasta {item.cap} con envío</Text> : null}
                {quantity ? null : <View style={styles.pick}><Text style={styles.pickText}>Elegir</Text></View>}
              </Pressable>
              {quantity ? (
                <View style={styles.stepper}>
                  {/* Enabled at the limits too, doing nothing there: a disabled one let the tap reach the toggle. */}
                  <Pressable onPress={() => { if (!busy && quantity > 1) step(index, -1); }} hitSlop={6}
                    accessibilityRole="button" accessibilityLabel={`Una menos de ${item.title}`}
                    accessibilityState={{ disabled: busy || quantity <= 1 }} style={styles.stepButton}>
                    <Icon name="minus" size={16} color={quantity <= 1 ? '#9CA3AF' : '#FFFFFF'} />
                  </Pressable>
                  <Text style={styles.quantity} accessibilityLabel={`Cantidad: ${quantity}`}>{String(quantity)}</Text>
                  <Pressable onPress={() => { if (!busy && quantity < most) step(index, 1); }} hitSlop={6}
                    accessibilityRole="button" accessibilityLabel={`Una más de ${item.title}`}
                    accessibilityState={{ disabled: busy || quantity >= most }} style={styles.stepButton}>
                    <Icon name="plus" size={16} color={quantity >= most ? '#9CA3AF' : '#FFFFFF'} />
                  </Pressable>
                </View>
              ) : null}
            </View>
          );
        }}
      />
      {units ? (
        <>
          <Button title={`Comprar ${units} ${units === 1 ? 'producto' : 'productos'}`} loading={picking === 'pick'}
            disabled={busy} onPress={() => { onBuy(items, top); }}
            accessibilityLabel={`Comprar ${units} ${units === 1 ? 'producto' : 'productos'}${top ? `, hasta ${top} con envío` : ''}`} />
          {/* The whole cart's top total, said before the tap: tapping approves up to it. */}
          <Text style={styles.cartCap}>
            {top ? `Hasta ${top} con envío. Si cuesta más, te pregunto antes de pedirlo.`
              : 'Te muestro el total antes de pedirlo.'}
          </Text>
        </>
      ) : (
        <Text style={styles.cartCap}>Elige uno o más productos y cuántos de cada uno.</Text>
      )}
    </View>
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
      {/* What is true, said plainly: it is kept, encrypted, for signing in at this store only. */}
      <View style={styles.assurance} accessible accessibilityRole="text">
        <Icon name="lock" size={14} color={colors.onHeroField} />
        <Text style={styles.assuranceText}>
          Se guarda cifrada y solo se usa para iniciar sesión en {site}. Puedes borrarla cuando quieras en «Tiendas
          con tu sesión».
        </Text>
      </View>
    </View>
  );
}

const NEW_FIELDS: { key: keyof AgentNewAddress; label: string; required?: boolean; phone?: boolean }[] = [
  { key: 'name', label: 'Nombre de quien recibe', required: true },
  { key: 'phone', label: 'Teléfono', required: true, phone: true },
  { key: 'street', label: 'Calle', required: true },
  { key: 'number', label: 'Número' },
  { key: 'apartment', label: 'Depto., piso (opcional)' },
  { key: 'neighborhood', label: 'Colonia o barrio' },
  { key: 'city', label: 'Ciudad', required: true },
  { key: 'state', label: 'Estado o provincia' },
  { key: 'postalCode', label: 'Código postal' },
  { key: 'references', label: 'Referencias (opcional)' },
];
const EMPTY_ADDRESS: AgentNewAddress = { name: '', phone: '', street: '', number: '', apartment: '', neighborhood: '',
  city: '', state: '', postalCode: '', references: '' };

const pick = (from: Partial<AgentNewAddress>): AgentNewAddress => Object.fromEntries(
  NEW_FIELDS.map((f) => [f.key, String(from[f.key] ?? '').trim()])) as AgentNewAddress;

// The one line the store is checked against: what the person confirms before anything is typed at the store.
export const addressLine = (a: AgentNewAddress) => [[a.street, a.number].filter(Boolean).join(' '), a.apartment,
  a.neighborhood, a.city, a.state, a.postalCode].map((part) => part.trim()).filter(Boolean).join(', ');

// A new delivery address: written here, read back whole, and only then sent to be added at the store.
function NewAddress({ draft, open, sending, disabled, onSend }: {
  draft: AgentNewAddress | null; open: boolean; sending: boolean; disabled: boolean;
  onSend: (address: AgentNewAddress) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(open);
  const [reviewing, setReviewing] = useState(false);
  // Only the address's own keys: a query result also carries __typename, which the mutation would refuse.
  const [address, setAddress] = useState<AgentNewAddress>(() => pick(draft ?? EMPTY_ADDRESS));
  const clean = pick(address);
  const ready = NEW_FIELDS.every((f) => !f.required || clean[f.key]);
  if (!editing) {
    return (
      <Pressable onPress={() => setEditing(true)} accessibilityRole="button" accessibilityLabel="Otra dirección"
        style={styles.addressOption} disabled={disabled}>
        <Icon name="plus" size={16} color={colors.primaryDark} />
        <Text style={styles.addressText}>Otra dirección</Text>
      </Pressable>
    );
  }
  if (reviewing) {
    return (
      <View style={styles.form}>
        <Text style={styles.message}>La agrego en la tienda así, tal cual:</Text>
        <Text style={styles.addressText}>{clean.name} · {clean.phone}</Text>
        <Text style={styles.addressText}>{addressLine(clean)}</Text>
        {clean.references ? <Text style={styles.address}>{clean.references}</Text> : null}
        <Button title="Confirmar dirección" loading={sending} disabled={disabled}
          onPress={() => { onSend(clean); }} />
        <Pressable onPress={() => setReviewing(false)} accessibilityRole="button" accessibilityLabel="Corregir"
          style={styles.link} disabled={disabled}>
          <Text style={styles.linkText}>Corregir</Text>
        </Pressable>
      </View>
    );
  }
  return (
    <View style={styles.form}>
      {NEW_FIELDS.map((f) => (
        <TextInput key={f.key} style={styles.input} value={address[f.key]} placeholder={f.label}
          placeholderTextColor="#9CA3AF" accessibilityLabel={f.label} maxLength={80}
          keyboardType={f.phone ? 'phone-pad' : 'default'}
          onChangeText={(value) => setAddress((was) => ({ ...was, [f.key]: value }))} />
      ))}
      <Button title="Revisar dirección" disabled={!ready || disabled} onPress={() => setReviewing(true)} />
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
  managing: { alignSelf: 'flex-start' },
  request: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', padding: 10, borderRadius: 10,
    backgroundColor: colors.primaryLight },
  requestBody: { flex: 1, gap: 2 },
  requestText: { fontSize: 15, fontWeight: '700', color: colors.onHeroField },
  requestButton: { fontSize: 12, color: colors.onHeroField },
  assurance: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, padding: 10, borderRadius: 10,
    backgroundColor: colors.primaryLight },
  assuranceText: { flex: 1, fontSize: 12, lineHeight: 17, color: colors.onHeroField },
  stepRow: { marginTop: 12, gap: 4 },
  address: { fontSize: 13, color: '#6B7280', marginTop: 4 },
  changeAddress: { alignSelf: 'flex-start', minHeight: 32, justifyContent: 'center' },
  addresses: { marginTop: 12, gap: 8 },
  addressOption: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12, paddingHorizontal: 12,
    borderRadius: 12, borderWidth: 1, borderColor: '#E5E7EB', minHeight: 48 },
  addressText: { flex: 1, fontSize: 14, color: colors.text.primary },
  line: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 },
  lineLabel: { fontSize: 13, color: '#6B7280' },
  lineValue: { fontSize: 13, color: '#6B7280', fontVariant: ['tabular-nums'] },
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
  choose: { gap: 8 },
  productChosen: { borderColor: colors.primaryDark, borderWidth: 2 },
  stepper: {
    minHeight: 40, borderRadius: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: colors.primaryDark, marginTop: 2, paddingHorizontal: 4,
  },
  stepButton: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  quantity: { fontSize: 16, fontWeight: '700', color: '#FFFFFF', fontVariant: ['tabular-nums'] },
  cartCap: { fontSize: 13, color: '#6B7280', textAlign: 'center' },
  product: {
    width: 156, padding: 10, borderRadius: 14, borderWidth: 1, borderColor: '#E5E7EB',
    backgroundColor: colors.background, gap: 6,
  },
  title: { fontSize: 14, lineHeight: 19, color: colors.text.primary },
  price: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  cap: { fontSize: 12, color: '#6B7280', marginTop: 2 },
  rating: { fontSize: 13, color: '#B45309', marginTop: 2 },
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
