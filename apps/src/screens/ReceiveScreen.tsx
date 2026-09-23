import React, { useCallback, useMemo } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Share } from 'react-native';
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
import { useRampFlows } from '../hooks/useRampFlows';
import { MainStackParamList } from '../types/navigation';
import { getCountryByIso } from '../utils/countries';
import { buildInviteLink } from '../utils/inviteLinks';

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
  const { receivePrimary, receiveMore } = useLocalRailOptions();
  const cryptoOptions = useCryptoReceiveOptions();

  const phoneDisplay = useMemo(() => {
    const number = userProfile?.phoneNumber;
    if (!number) return null;
    const country = userProfile?.phoneCountry ? getCountryByIso(userProfile.phoneCountry) : null;
    return country ? `${country[1]} ${number}` : number;
  }, [userProfile?.phoneNumber, userProfile?.phoneCountry]);

  // The share doubles as an invite: the payer may not have Confío yet, and
  // the link carries this user's referral so the install is credited.
  const handleSharePhone = useCallback(() => {
    if (!phoneDisplay) return;
    const lines = [
      `Envíame dólares por Confío a mi número ${phoneDisplay}.`,
    ];
    if (userProfile?.username) {
      lines.push('', `¿Aún no tienes Confío? ${buildInviteLink({ username: userProfile.username, source: 'receive' })}`);
    }
    Share.share({ message: lines.join('\n') }).catch(() => {});
  }, [phoneDisplay, userProfile?.username]);

  // Where no ramp provider operates there is no one-off recharge to offer;
  // the cash row below is the way in.
  const rechargeRow: RouteOption | null = isRampBlocked ? null : {
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
          ) : phoneDisplay ? (
            <RouteCard label="DE ALGUIEN EN CONFÍO">
              <View style={styles.phoneRow}>
                <View style={styles.phoneIcon}>
                  <Icon name="smartphone" size={20} color={colors.primaryDark} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.phoneNumber}>{phoneDisplay}</Text>
                  <Text style={styles.phoneHint}>Te envían dólares a tu número</Text>
                </View>
                <TouchableOpacity
                  style={styles.shareButton}
                  onPress={handleSharePhone}
                  accessibilityRole="button"
                  accessibilityLabel="Compartir mi número"
                >
                  <Icon name="share-2" size={16} color={colors.white} />
                  <Text style={styles.shareButtonText}>Compartir</Text>
                </TouchableOpacity>
              </View>
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
  phoneRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 8,
  },
  phoneIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  phoneNumber: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text.primary,
  },
  phoneHint: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 2,
  },
  shareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.primaryDark,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
  },
  shareButtonText: {
    color: colors.white,
    fontSize: 13,
    fontWeight: '700',
  },
});
