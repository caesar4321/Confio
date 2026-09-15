import React, { useState } from 'react';
import { SafeAreaView, ScrollView, StatusBar, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { getDiditResultSessionId, startDiditVerification } from '../services/diditService';
import { createAdditionalDocumentSession, syncAdditionalDocument } from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'AdditionalDocument'>;
type Route = RouteProp<MainStackParamList, 'AdditionalDocument'>;

// A second identity document of the same person, for a local-money rail the
// primary one does not satisfy (a Venezuelan cédula cannot open a Colombian
// account; a passport can). It never replaces the primary verification, which
// Recarga/Retiro keep using — the copy says so, because that is exactly the
// worry this screen has to answer.
function acceptedDocument(idCountry: string, types: string[]): string {
  if (idCountry === 'ARG') {
    return 'DNI o pasaporte argentino';
  }
  if (types.length === 1 && types[0] === 'P') {
    return 'Pasaporte vigente de cualquier país';
  }
  return 'Pasaporte o documento de identidad de otro país';
}

type Result = { variant: 'success' | 'info' | 'error'; message: string } | null;

export default function AdditionalDocumentScreen() {
  const navigation = useNavigation<Nav>();
  const params = useRoute<Route>().params || {};
  const idCountry = params.idCountry || '';
  const documentTypes = params.documentTypes?.length ? params.documentTypes : ['P'];
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [done, setDone] = useState(false);

  const title = idCountry === 'ARG'
    ? 'Verifica tu DNI argentino'
    : documentTypes.length === 1 && documentTypes[0] === 'P' ? 'Verifica tu pasaporte' : 'Verifica otro documento';

  const verify = async () => {
    setBusy(true);
    setResult(null);
    try {
      const session = await createAdditionalDocumentSession(idCountry, documentTypes);
      // Left while the session was being created: never open Didit over another screen.
      if (!navigation.isFocused()) return;
      const sdk = await startDiditVerification(session.sessionToken);
      if (sdk?.type === 'cancelled') {
        setResult({ variant: 'info', message: 'Cancelaste la verificación. Puedes retomarla cuando quieras.' });
        return;
      }
      if (sdk?.type === 'failed') {
        throw new Error(sdk?.errorMessage || 'No se pudo completar la verificación.');
      }
      const outcome = await syncAdditionalDocument(getDiditResultSessionId(sdk, session.sessionId) || session.sessionId);
      if (outcome.status === 'verified') {
        setDone(true);
        setResult({ variant: 'success', message: 'Listo: tu documento quedó verificado.' });
      } else if (outcome.status === 'rejected') {
        setResult({ variant: 'error', message: outcome.detail || 'No pudimos verificar este documento.' });
      } else {
        setResult({ variant: 'info', message: 'Estamos revisando tu documento. Te avisaremos apenas termine.' });
      }
    } catch (error: any) {
      setResult({ variant: 'error', message: error?.message || 'No se pudo completar la verificación.' });
    } finally {
      setBusy(false);
    }
  };

  const rows: [string, string, string][] = [
    ['file-text', 'Documento aceptado', acceptedDocument(idCountry, documentTypes)],
    ['user-check', 'Tus mismos datos', 'El nombre y la fecha de nacimiento deben coincidir con tu verificación actual.'],
    ['shield', 'Tu verificación actual no cambia', 'Recarga y Retiro siguen usando el documento que ya verificaste.'],
    ['clock', 'Unos 2 minutos', 'Una foto del documento y una selfie.'],
  ];

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Otro documento"
            title={title}
            subtitle={params.reason
              || 'Algunas transferencias locales aceptan un documento distinto al que ya verificaste.'}
            onBack={() => navigation.goBack()}
          />
        </RampReveal>
        <RampReveal delay={80}>
          <View style={styles.section}>
            <RampStepHeader number={1} title="Qué necesitas" accentColor={colors.primaryDark}
              accentBackground={colors.primaryLight} titleColor={colors.dark} />
            <View style={styles.inputCard}>
              {rows.map(([icon, heading, body]) => (
                <View key={heading} style={[styles.reviewRow, { alignItems: 'center' }]}>
                  <View style={styles.methodIcon}>
                    <Icon name={icon} size={18} color={colors.primary} />
                  </View>
                  <View style={styles.methodCopy}>
                    <Text style={styles.methodTitle}>{heading}</Text>
                    <Text style={styles.methodText}>{body}</Text>
                  </View>
                </View>
              ))}
            </View>
            {result ? (
              <View style={result.variant === 'error' ? styles.warningCard : [styles.disclaimerPill, { marginTop: 14 }]}>
                <Icon name={result.variant === 'success' ? 'check-circle' : result.variant === 'error' ? 'alert-triangle' : 'info'}
                  size={16} color={result.variant === 'error' ? colors.warning.icon : colors.primaryDark} />
                <Text style={result.variant === 'error' ? [styles.warningText, { flex: 1, marginTop: 0 }] : styles.quoteNote}>
                  {result.message}
                </Text>
              </View>
            ) : null}
          </View>
        </RampReveal>
        <RampActionBar
          primaryLabel={done ? 'Continuar' : 'Verificar con Didit'}
          onPrimaryPress={done ? () => navigation.goBack() : verify}
          primaryLoading={busy}
          primaryIconName={done ? 'chevron-right' : 'shield'}
        />
      </ScrollView>
    </SafeAreaView>
  );
}
