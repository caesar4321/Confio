import React from 'react';
import { View, StyleSheet, ScrollView, Share } from 'react-native';
import { Text } from '../components/common/AppText';
import { buildInviteLink } from '../utils/inviteLinks';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import { GET_MY_BALANCES } from '../apollo/queries';
import { RouteOption, RouteOptionRow } from '../components/RouteSheet';
import { AdvancedCard, LocalRailsCard, RouteCard } from '../components/RouteCard';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useCryptoReceiveOptions } from '../hooks/useCryptoReceiveOptions';
import { useLocalRailOptions } from '../hooks/useLocalRailOptions';
import { useKoyweReplaced } from '../hooks/useKoyweReplaced';
import { useRampFlows } from '../hooks/useRampFlows';
import { MainStackParamList } from '../types/navigation';
import { QrShowIcon } from '../components/QrPayIcon';

type Nav = NativeStackNavigationProp<MainStackParamList>;

/**
 * Recibir — every way money reaches this user, in one place.
 *
 * The two-verb IA: Recargar is "receive from my own bank", so it lives here
 * rather than as its own Home button. Order is by how often each is the
 * answer: another Confío user, then a bank or wallet, then (collapsed) a
 * crypto address.
 *
 * Inside "bank or wallet" there are two different products and the copy has
 * to keep them apart:
 *   - Recargar ahora (Koywe/Guardarian): you pick an amount and pay that one
 *     order. No setup. Stays even after a local account exists — it is the
 *     fallback when the account's key is processing or the provider is down.
 *   - Tu propia cuenta (Infinia and friends): a standing account anyone can
 *     pay into at any time. Opening it may cost a server-quoted fee, which
 *     the application flow shows — never hardcode it here.
 * Where no ramp provider operates (VE, NI, PA, CU), the first row becomes the
 * cash directory: for those users it is the only fiat door there is.
 */
export default function ReceiveScreen() {
  const navigation = useNavigation<Nav>();
  const { userProfile } = useAuth() as any;
  const { activeAccount } = useAccount();
  // A business gets paid through Cobrar (an invoice QR), not through the
  // owner's personal phone number.
  const isBusiness = activeAccount?.type?.toLowerCase() === 'business';

  // Home already loaded this; cache-first keeps Recibir instant. It only
  // decides whether the legacy-cUSD door shows in the recharge picker.
  const { data: balancesData } = useQuery(GET_MY_BALANCES, { fetchPolicy: 'cache-first' });
  const legacyCusdBalance = parseFloat(balancesData?.myBalances?.cusd || '0');

  const { openRechargeFlow, sheets, isRampBlocked } = useRampFlows({ legacyCusdBalance });
  // QR Bolivia takes over the one-off recharge for Bolivians while it is on.
  const koyweReplaced = useKoyweReplaced();
  const { receivePrimary, receiveMore } = useLocalRailOptions();
  const cryptoOptions = useCryptoReceiveOptions();


  // Friends pay a @usuario (Enviar a un @usuario). A seller paid by many
  // people is nudged, then blocked, toward Cobrar (users/direct_receive.py).
  const directStatus = (userProfile?.directReceiveStatus || 'ok') as string;
  const usernameRow: RouteOption | null = userProfile?.username ? (
    directStatus === 'blocked'
      ? {
        id: 'username_blocked',
        icon: 'at-sign',
        title: `@${userProfile.username}`,
        subtitle: 'Tu cuenta cobra con QR: los envíos a tu usuario están pausados',
        onPress: () => navigation.navigate('Charge'),
      }
      : {
        id: 'username_share',
        icon: 'at-sign',
        title: `@${userProfile.username}`,
        subtitle: directStatus === 'nudge'
          ? '¿Vendés? Cobrá con QR. Tus amigos te envían a tu usuario'
          : 'Tus amigos te envían dólares a tu usuario · Compartir',
        onPress: () => {
          const lines = [
            `Envíame dólares por Confío a mi usuario @${userProfile.username}.`,
            '',
            `¿Aún no tienes Confío? ${buildInviteLink({ username: userProfile.username, source: 'receive' })}`,
          ];
          Share.share({ message: lines.join('\n') }).catch(() => {});
        },
      }
  ) : null;

  // Where no ramp provider operates there is no one-off recharge to offer;
  // the cash row below is the way in.
  const rechargeRow: RouteOption | null = isRampBlocked || koyweReplaced.topUp ? null : {
    id: 'recharge_now',
    icon: 'plus-circle',
    title: 'Recargar ahora',
    subtitle: 'Eliges el monto y pagas desde tu banco',
    onPress: openRechargeFlow,
  };
  // The old Efectivo menu: a directory, offered everywhere.
  const cashRow: RouteOption = {
    id: 'cash_directory',
    icon: 'map-pin',
    title: 'Efectivo con un agente',
    subtitle: 'Financieras locales verificadas cerca de ti',
    onPress: () => navigation.navigate('Financieras'),
  };


  // Every row below is the owner's alone (bank rails are owner_only server-
  // side, CreateRampOrder refuses employees). Home never offers employees
  // Recibir, but an account switch can leave this screen mounted under them.
  if (activeAccount?.isEmployee) {
    return (
      <View style={[styles.container, styles.body]}>
        <RouteCard label="SOLO PARA EL DUEÑO">
          <Text style={styles.phoneHint}>
            Recibir desde bancos y billeteras es exclusivo del dueño del negocio. Para cobrar a clientes usa Cobrar.
          </Text>
        </RouteCard>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header: the same stack header as Enviar (ReceiveStackHeader) —
          mirror screens start from the same chrome. */}
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>

        <View style={styles.body}>
          {isBusiness ? (
            <RouteCard label="DE TUS CLIENTES">
              <RouteOptionRow
                first
                option={{
                  id: 'charge',
                  icon: 'dollar-sign',
                  title: 'Cobrar',
                  subtitle: 'Crea un cobro y muéstrale el QR a tu cliente',
                  // popTo, not navigate: React Navigation 7 would push a
                  // second tab shell on top of this screen.
                  onPress: () => navigation.popTo('BottomTabs', { screen: 'Charge' } as any),
                }}
              />
            </RouteCard>
          ) : usernameRow ? (
            <RouteCard label="DE ALGUIEN EN CONFÍO">
              <RouteOptionRow first option={usernameRow} />
            </RouteCard>
          ) : null}

          {/* Same card as Enviar's, mirrored: the own-money row (the old
              Recargar) always leads, as "A mi propia cuenta" does there.
              Other countries sit behind "Más países". */}
          <LocalRailsCard
            label="DESDE UN BANCO O BILLETERA"
            leading={rechargeRow ? [rechargeRow] : []}
            primary={receivePrimary}
            more={receiveMore}
            moreTitle="¿Dónde quieres recibir?"
          />

          {/* A person charges like a shop: much of LATAM's commerce runs
              under someone's own name. Same invoice QR and 0.9% as a
              business; the stack Charge screen, since the tab is business-only.
              Below the bank row and named for what it is: placed first, 37
              people in Bolivia made a charge QR in one week thinking it was
              the top-up, and their banks rejected it (2026-10-21). */}
          {!isBusiness ? (
            <RouteCard label="DE OTRO USUARIO DE CONFÍO">
              <RouteOptionRow
                first
                option={{
                  id: 'charge',
                  icon: 'dollar-sign',
                  iconNode: <QrShowIcon size={20} color={colors.primaryDark} />,
                  title: 'Cobrar con QR de Confío',
                  subtitle: 'Se paga desde la app Confío, no desde un banco',
                  onPress: () => navigation.navigate('Charge'),
                }}
              />
            </RouteCard>
          ) : null}

          <RouteCard label="EN EFECTIVO">
            <RouteOptionRow option={cashRow} first />
          </RouteCard>

          <AdvancedCard subtitle="Recibir con dirección cripto" options={cryptoOptions} />
        </View>
      </ScrollView>
      {sheets}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    // Enviar's background, so the two verbs read as one pair.
    backgroundColor: colors.white,
  },
  content: {
    paddingBottom: 40,
  },
  body: {
    paddingHorizontal: 16,
    paddingTop: 16,
    gap: 14,
  },
  phoneHint: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 2,
  },
});
