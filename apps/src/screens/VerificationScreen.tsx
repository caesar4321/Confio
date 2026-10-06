import React from 'react';
import {
  ActivityIndicator,
  AppState,
  Linking,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Text } from '../components/common/AppText';
import { CompositeNavigationProp, NavigationProp, RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { gql, useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Header } from '../navigation/Header';
import { MainStackParamList, RootStackParamList } from '../types/navigation';
import { GET_BUSINESS_KYC_STATUS, GET_ME, GET_MY_PERSONAL_KYC_STATUS } from '../apollo/queries';
import {
  CREATE_DIDIT_BROWSER_VERIFICATION_SESSION,
  CREATE_DIDIT_VERIFICATION_SESSION,
  SYNC_DIDIT_VERIFICATION_SESSION,
} from '../apollo/mutations';
import { useAccount } from '../contexts/AccountContext';
import { useRampCountry } from '../hooks/useRampCountry';
import { getDiditResultSessionId, startDiditVerification } from '../services/diditService';
import { countryName } from '../config/localRails';
import { AnalyticsService } from '../services/analyticsService';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';

// Its own document: an older server without the field fails only this list,
// and the screen falls back to the single verification status.
const MY_IDENTITY_DOCUMENTS = gql`
  query MyIdentityDocuments {
    myIdentityDocuments {
      id
      documentType
      issuingCountry
      status
      rejectedReason
      isAdditional
      verifiedAt
      localCountries
    }
  }
`;

// Only Didit's own hosted verification page is ever opened in the browser.
const DIDIT_SESSION_URL = /^https:\/\/verify\.didit\.me(?::443)?\/(?:[a-z]{2}\/)?session\/[A-Za-z0-9_-]+\/?(?:[?#].*)?$/i;

const openDiditSessionUrl = async (url: unknown, unsafeMessage: string) => {
  if (typeof url !== 'string' || !DIDIT_SESSION_URL.test(url)) throw new Error(unsafeMessage);
  try {
    await Linking.openURL(url);
  } catch {
    // The native error quotes the URL, a bearer link: never show it.
    throw new Error('No encontramos un navegador para abrir la verificación.');
  }
};

const DIDIT_SESSION_ID = /^[A-Za-z0-9_-]+$/;

// The server's own message, never a raw GraphQL or transport error.
function userFacingMessage(error: any): string | null {
  return error?.graphQLErrors?.length || error?.networkError ? null : error?.message || null;
}

type NormalizedStatus = 'unverified' | 'pending' | 'verified' | 'rejected';

type IdentityDocument = {
  id: string;
  documentType: string;
  issuingCountry: string;
  status: string;
  rejectedReason?: string | null;
  isAdditional: boolean;
  verifiedAt: string | null;
  localCountries: string[];
};

// The three things verification unlocks, explained once, in the same order
// every document card uses below.
const FEATURES = {
  rewards: {
    icon: 'gift',
    title: 'Recompensas',
    body: 'Reclama los $CONFIO que ganas al invitar amigos y con tus logros.',
  },
  ramps: {
    icon: 'repeat',
    title: 'Recargar y retirar',
    body: 'Recargar es comprar dólares digitales desde tu banco. Retirar es pasarlos de vuelta a tu banco.',
  },
  local: {
    icon: 'globe',
    title: 'Cuentas locales',
    body: 'Tu propia llave Bre-B, CLABE, Pix o CVU para recibir y enviar en moneda local.',
  },
} as const;
type FeatureKey = keyof typeof FEATURES;

// Local accounts the app can open today, in the order people look for them.
const LOCAL_ACCOUNTS = ['CO', 'MX', 'BR', 'AR'];

// What people call the ID in each country; a passport is a passport everywhere.
const ID_NAME: Record<string, string> = {
  AR: 'DNI', PE: 'DNI', MX: 'INE', BR: 'RG', CO: 'Cédula', VE: 'Cédula', EC: 'Cédula', PY: 'Cédula',
  UY: 'Cédula', CL: 'Cédula', BO: 'Cédula',
};

function documentLabel(doc: IdentityDocument): string {
  if (doc.documentType === 'passport') return 'Pasaporte';
  if (doc.documentType === 'drivers_license') return 'Licencia de conducir';
  if (doc.documentType === 'foreign_id') return 'Documento de extranjería';
  return ID_NAME[doc.issuingCountry] || 'Documento de identidad';
}

function normalizeStatus(value?: string | null): NormalizedStatus {
  const normalized = (value || '').trim().toLowerCase();
  if (['pending', 'submitted', 'in_review', 'in review', 'review required', 'in progress', 'awaiting user', 'resubmission requested', 'resubmission required', 'resub_requested', 'resubmitted', 'awaiting_user'].includes(normalized)) return 'pending';
  if (['verified', 'approved', 'completed', 'success'].includes(normalized)) return 'verified';
  if (['rejected', 'declined', 'failed', 'denied'].includes(normalized)) return 'rejected';
  return 'unverified';
}

const STATUS_META: Record<NormalizedStatus, { label: string; color: string; bg: string; icon: string }> = {
  verified: { label: 'Verificado', color: colors.success, bg: colors.successLight, icon: 'check-circle' },
  pending: { label: 'En revisión', color: colors.warning.icon, bg: colors.warningLight, icon: 'clock' },
  rejected: { label: 'Rechazado', color: colors.danger, bg: colors.dangerLight, icon: 'x-circle' },
  unverified: { label: 'Sin verificar', color: colors.info, bg: colors.infoLight, icon: 'shield' },
};

const joinNames = (names: string[]) =>
  names.length > 1 ? `${names.slice(0, -1).join(', ')} y ${names[names.length - 1]}` : names[0] || '';

function StatusPill({ status }: { status: NormalizedStatus }) {
  const meta = STATUS_META[status];
  return (
    <View style={[styles.statusPill, { backgroundColor: meta.bg }]}>
      <Icon name={meta.icon} size={13} color={meta.color} />
      <Text style={[styles.statusPillText, { color: meta.color }]}>{meta.label}</Text>
    </View>
  );
}

type Capability = { feature: FeatureKey; allowed: boolean; detail: string };

/**
 * What one verified document opens, feature by feature, described the same
 * way whichever country issued it.
 */
function capabilities(doc: IdentityDocument, phoneCountryName: string, rampBlocked: boolean): Capability[] {
  const ramps: Capability = doc.isAdditional
    ? { feature: 'ramps', allowed: false, detail: 'Solo con el documento del país de tu teléfono.' }
    : rampBlocked
      ? { feature: 'ramps', allowed: false, detail: `Aún no disponible${phoneCountryName ? ` en ${phoneCountryName}` : ' en tu país'}.` }
      : { feature: 'ramps', allowed: true, detail: phoneCountryName ? `Con bancos de ${phoneCountryName}.` : 'Con bancos de tu país.' };
  const open = LOCAL_ACCOUNTS.filter(country => doc.localCountries.includes(country)).map(countryName);
  const local: Capability = open.length
    ? { feature: 'local', allowed: true, detail: `En ${joinNames(open)}.` }
    : {
      feature: 'local', allowed: false,
      detail: doc.issuingCountry === 'VE'
        ? 'No se aceptan con este documento. Agrega un pasaporte o un documento de otro país.'
        : 'No disponibles con este documento.',
    };
  return [
    { feature: 'rewards', allowed: true, detail: 'Incluidas.' },
    ramps,
    local,
  ];
}

const VerificationScreen = () => {
  const navigation = useNavigation<CompositeNavigationProp<NavigationProp<MainStackParamList>, NavigationProp<RootStackParamList>>>();
  const route = useRoute<RouteProp<MainStackParamList, 'Verification'>>();
  const { activeAccount } = useAccount();
  const isBusinessAccount = (activeAccount?.type || '').toLowerCase() === 'business';
  const { countryCode: phoneCountry, isBlocked: rampBlocked } = useRampCountry();
  const phoneCountryName = phoneCountry ? countryName(phoneCountry) : '';

  const { data: meData, refetch: refetchMe, loading: meLoading } = useQuery(GET_ME, { fetchPolicy: 'network-only' });
  const { data: personalKycData, refetch: refetchPersonalKyc, loading: personalLoading } = useQuery(GET_MY_PERSONAL_KYC_STATUS, { fetchPolicy: 'network-only' });
  const { data: bizKycData, refetch: refetchBizKyc, loading: businessLoading } = useQuery(
    GET_BUSINESS_KYC_STATUS,
    {
      variables: { businessId: activeAccount?.business?.id || '' },
      skip: !isBusinessAccount || !activeAccount?.business?.id,
      fetchPolicy: 'network-only',
    },
  );
  const documentsQuery = useQuery(MY_IDENTITY_DOCUMENTS, {
    skip: isBusinessAccount, fetchPolicy: 'network-only', errorPolicy: 'all',
  });
  const refetchDocuments = documentsQuery.refetch;
  const documents: IdentityDocument[] | null = documentsQuery.data?.myIdentityDocuments || null;

  const [createDiditSession] = useMutation(CREATE_DIDIT_VERIFICATION_SESSION);
  const [syncDiditSession] = useMutation(SYNC_DIDIT_VERIFICATION_SESSION);
  const [createDiditBrowserSession] = useMutation(CREATE_DIDIT_BROWSER_VERIFICATION_SESSION);
  // True while the user verifies on Didit's page in the browser: the next return
  // to the app refreshes once. Didit's redirect back is synced separately below.
  const awaitingBrowserRef = React.useRef(false);
  // The active account is null until AccountContext loads; a redirect that
  // cold-started the app must wait for it to know personal from business.
  const accountReady = !!activeAccount;

  const [isLaunchingDidit, setIsLaunchingDidit] = React.useState(false);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [isSyncingRedirect, setIsSyncingRedirect] = React.useState(false);
  const [banner, setBanner] = React.useState<{ message: string; variant: 'error' | 'success' | 'info' | 'warning' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);

  const personalStatus = normalizeStatus(personalKycData?.myPersonalKycStatus?.status || meData?.me?.verificationStatus);
  const businessStatus = normalizeStatus(bizKycData?.businessKycStatus?.status);
  const effectiveStatus = isBusinessAccount
    ? businessStatus
    : personalStatus;
  const effectiveDetail = isBusinessAccount
    ? bizKycData?.businessKycStatus?.statusDetail
    : personalKycData?.myPersonalKycStatus?.statusDetail;
  const isBusy = isLaunchingDidit || isRefreshing || isSyncingRedirect;
  const isInitialLoading = meLoading || personalLoading || businessLoading
    || (!isBusinessAccount && documentsQuery.loading && !documents);

  const refreshStatuses = React.useCallback(async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        refetchMe(),
        refetchPersonalKyc(),
        isBusinessAccount && refetchBizKyc ? refetchBizKyc() : Promise.resolve(),
        isBusinessAccount ? Promise.resolve() : refetchDocuments().catch(() => undefined),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  }, [isBusinessAccount, refetchBizKyc, refetchMe, refetchPersonalKyc, refetchDocuments]);

  useFocusEffect(
    React.useCallback(() => {
      refreshStatuses().catch(() => {});
    }, [refreshStatuses]),
  );

  const syncSessionAndRefresh = React.useCallback(async (sessionId: string) => {
    const { data } = await syncDiditSession({ variables: { sessionId } });
    const result = data?.syncDiditVerificationSession;
    if (!result?.success) {
      throw new Error(result?.error || 'No se pudo sincronizar la decisión de Didit.');
    }
    await refreshStatuses();
    const normalized = normalizeStatus(result.verificationStatus);
    const detail = result.statusDetail || result.verification?.statusDetail;
    if (normalized === 'verified') {
      const analyticsParams = { method: 'didit', provider: 'didit', verification_status: 'verified', session_id: sessionId };
      void AnalyticsService.logEvent('generate_lead', analyticsParams);
      void AnalyticsService.logEvent('didit_verified', analyticsParams);
      setBanner({ variant: 'success', message: detail || (isBusinessAccount ? 'Tu negocio quedó verificado correctamente.' : 'Tu identidad quedó verificada correctamente.') });
    } else if (normalized === 'pending') {
      setBanner({ variant: 'info', message: detail || 'Didit recibió tu sesión. Te avisaremos cuando termine la revisión.' });
    } else if (normalized === 'rejected') {
      setBanner({ variant: 'error', message: detail || 'La sesión fue rechazada. Puedes intentar nuevamente.' });
    } else {
      setBanner({ variant: 'info', message: detail || 'La sesión se creó, pero Didit todavía no devolvió un resultado final.' });
    }
  }, [isBusinessAccount, refreshStatuses, syncDiditSession]);

  React.useEffect(() => {
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active' || !(isBusinessAccount || awaitingBrowserRef.current)) return;
      awaitingBrowserRef.current = false;
      refreshStatuses().catch(() => {});
    });
    return () => listener.remove();
  }, [isBusinessAccount, refreshStatuses]);

  // Didit's redirect back (confio://verification?verificationSessionId=…)
  // reaches this screen as route params through the navigation linking config,
  // warm or cold start alike. Sync the session it names; the server checks it
  // belongs to this user. Business keeps its webhook + refresh.
  const redirectedSessionId = route.params?.verificationSessionId;
  const handledRedirectRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    // The active account is unknown until AccountContext loads.
    if (!redirectedSessionId) {
      // Params cleared: a later redirect for the same session is new again.
      handledRedirectRef.current = null;
      return;
    }
    if (!accountReady || handledRedirectRef.current === redirectedSessionId) return;
    handledRedirectRef.current = redirectedSessionId;
    navigation.setParams({ verificationSessionId: undefined, status: undefined } as any);
    if (isBusinessAccount || !DIDIT_SESSION_ID.test(redirectedSessionId)) return;
    awaitingBrowserRef.current = false;
    setIsSyncingRedirect(true);
    // A redirect the server will not sync here (e.g. a business KYB session
    // while the personal account is active) is not the user's to fix: refresh
    // quietly and let the webhook record the decision.
    syncSessionAndRefresh(redirectedSessionId)
      .catch(() => refreshStatuses().catch(() => {}))
      .finally(() => setIsSyncingRedirect(false));
  }, [accountReady, isBusinessAccount, navigation, redirectedSessionId, refreshStatuses, syncSessionAndRefresh]);

  // A browser session belongs to the account that started it.
  React.useEffect(() => { awaitingBrowserRef.current = false; }, [isBusinessAccount]);

  // Business verification resumes its pending hosted session; personal
  // verification starts a new native session.
  const handleStartDidit = React.useCallback(async () => {
    setIsLaunchingDidit(true);
    awaitingBrowserRef.current = false;
    try {
      const { data } = await createDiditSession();
      const result = data?.createDiditVerificationSession;
      if (!result?.success || !result?.session?.sessionId) {
        throw new Error(result?.error || 'No se pudo crear la sesión de Didit.');
      }
      const createdSessionId = result.session.sessionId;
      if (isBusinessAccount) {
        await openDiditSessionUrl(result.session.sessionUrl, 'No se recibió un enlace seguro para verificar tu negocio.');
        setBanner({ variant: 'info', message: 'Completa los datos del negocio, sus documentos y las verificaciones de sus representantes en Didit. Al volver, actualiza esta pantalla para ver el resultado.' });
        await refreshStatuses();
        return;
      }
      const sdkResult = await startDiditVerification(result.session.sessionToken);
      if (sdkResult?.type === 'cancelled') {
        setBanner({ variant: 'warning', message: 'Cancelaste la verificación antes de terminarla.' });
        return;
      }
      if (sdkResult?.type === 'failed') {
        throw new Error(sdkResult?.errorMessage || 'No se pudo completar la verificación con Didit.');
      }
      const resolvedSessionId = getDiditResultSessionId(sdkResult, createdSessionId);
      if (!resolvedSessionId) {
        throw new Error('Didit no devolvió el identificador de sesión.');
      }
      await syncSessionAndRefresh(resolvedSessionId);
    } catch (error: any) {
      setBanner({ variant: 'error', message: error?.message || 'No se pudo completar la verificación con Didit.' });
    } finally {
      setIsLaunchingDidit(false);
    }
  }, [createDiditSession, isBusinessAccount, refreshStatuses, syncSessionAndRefresh]);

  // Fallback for devices where the in-app camera stays black: the same
  // verification on Didit's page, using the browser's camera.
  const handleStartDiditInBrowser = React.useCallback(async () => {
    setIsLaunchingDidit(true);
    try {
      const { data } = await createDiditBrowserSession();
      const result = data?.createDiditVerificationSession;
      const sessionId = result?.session?.sessionId;
      if (!result?.success || !sessionId) {
        throw new Error(result?.error || 'No se pudo crear la sesión de Didit.');
      }
      awaitingBrowserRef.current = true;
      await openDiditSessionUrl(result.session.sessionUrl, 'No se recibió un enlace seguro para verificarte en el navegador.');
      setBanner({ variant: 'info', message: 'Termina la verificación en tu navegador. Al volver, actualizaremos tu estado.' });
    } catch (error: any) {
      awaitingBrowserRef.current = false;
      // A server without `inBrowser` rejects the document (HTTP 400, surfaced by
      // Apollo as a network error).
      setBanner({ variant: 'error', message: userFacingMessage(error) || 'No se pudo abrir la verificación en el navegador.' });
    } finally {
      setIsLaunchingDidit(false);
    }
  }, [createDiditBrowserSession]);

  const browserFallback = (
    <TouchableOpacity onPress={handleStartDiditInBrowser} disabled={isBusy} accessibilityRole="button" style={styles.inlineAction}>
      <Icon name="globe" size={15} color={colors.primaryDark} />
      <Text style={styles.inlineActionText}>¿La cámara no se abre? Verifícate en el navegador</Text>
    </TouchableOpacity>
  );

  const openOtherDocument = () => (navigation as any).navigate('AdditionalDocument', { idCountry: '', documentTypes: ['P', 'ID'] });

  const list = documents || [];
  const verifiedCount = list.filter(doc => doc.status === 'verified').length;
  const hasPending = list.some(doc => doc.status === 'pending');
  const hasCountryAttempt = list.some(doc => !doc.isAdditional);
  // One browser fallback per screen: on the first unverified country document.
  // Not under a pending review: a second primary session would race it.
  const browserFallbackDocId = list.find(doc => !doc.isAdditional && normalizeStatus(doc.status) === 'rejected')?.id;

  // ─── Pieces ───

  const summary = (() => {
    const status: NormalizedStatus = verifiedCount ? 'verified' : hasPending ? 'pending' : effectiveStatus;
    const title = verifiedCount
      ? (verifiedCount === 1 ? 'Tienes 1 documento verificado' : `Tienes ${verifiedCount} documentos verificados`)
      : hasPending ? 'Estamos revisando tu documento' : 'Verifica tu identidad';
    const body = verifiedCount
      ? 'Abajo ves qué habilita cada uno. Puedes agregar otro documento cuando quieras.'
      : hasPending
        ? 'Suele tardar pocos minutos. Mientras tanto, puedes enviar otra verificación si te equivocaste.'
        : 'Con un documento verificado desbloqueas recompensas, recargas y retiros, y cuentas locales.';
    return (
      <View style={styles.summaryCard}>
        <View style={styles.summaryTop}>
          <View style={styles.summaryIcon}>
            <Icon name="shield" size={22} color={colors.primaryDark} />
          </View>
          <StatusPill status={status} />
        </View>
        <Text style={styles.summaryTitle}>{title}</Text>
        <Text style={styles.summaryBody}>{body}</Text>
      </View>
    );
  })();

  const featureGuide = (
    <View style={styles.section}>
      <Text style={styles.sectionLabel}>Qué desbloqueas</Text>
      <View style={styles.card}>
        {(Object.keys(FEATURES) as FeatureKey[]).map((key, index) => (
          <View key={key} style={[styles.guideRow, index > 0 && styles.divided]}>
            <View style={styles.featureIcon}>
              <Icon name={FEATURES[key].icon} size={18} color={colors.primaryDark} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.featureTitle}>{FEATURES[key].title}</Text>
              <Text style={styles.featureBody}>{FEATURES[key].body}</Text>
            </View>
          </View>
        ))}
      </View>
    </View>
  );

  const renderDocument = (doc: IdentityDocument) => {
    const status = normalizeStatus(doc.status);
    const country = doc.issuingCountry ? countryName(doc.issuingCountry) : '';
    const retry = doc.isAdditional ? openOtherDocument : handleStartDidit;
    return (
      <View key={doc.id} style={styles.card}>
        <View style={styles.documentHeader}>
          <View style={styles.documentIcon}>
            <Icon name={doc.documentType === 'passport' ? 'book' : 'credit-card'} size={18} color={colors.primaryDark} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.documentTitle}>
              {country || status === 'verified' ? `${documentLabel(doc)}${country ? ` · ${country}` : ''}` : 'Tu documento'}
            </Text>
            <Text style={styles.documentSubtitle}>
              {doc.isAdditional ? 'De otro país' : 'Del país de tu teléfono'}
            </Text>
          </View>
          <StatusPill status={status} />
        </View>

        {status === 'verified' ? (
          <View style={styles.capabilityList}>
            {capabilities(doc, phoneCountryName, rampBlocked).map(item => (
              <View key={item.feature} style={styles.capabilityRow}>
                <View style={[styles.capabilityMark, item.allowed ? styles.markYes : styles.markNo]}>
                  <Icon name={item.allowed ? 'check' : 'minus'} size={14} color={item.allowed ? colors.white : colors.textSecondary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.capabilityTitle, !item.allowed && styles.muted]}>{FEATURES[item.feature].title}</Text>
                  <Text style={styles.capabilityDetail}>{item.detail}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : status === 'pending' ? (
          <>
            <Text style={styles.note}>Estamos revisando este documento. Te avisaremos apenas termine.</Text>
            <TouchableOpacity onPress={retry} disabled={isBusy} accessibilityRole="button" style={styles.inlineAction}>
              <Icon name="refresh-cw" size={15} color={colors.primaryDark} />
              <Text style={styles.inlineActionText}>¿Te equivocaste? Envía otra verificación</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={styles.note}>
              {doc.rejectedReason || 'No pudimos verificar este documento. Inténtalo de nuevo o contacta a soporte si el problema continúa.'}
            </Text>
            <TouchableOpacity onPress={retry} disabled={isBusy} accessibilityRole="button" style={styles.inlineAction}>
              <Icon name="refresh-cw" size={15} color={colors.primaryDark} />
              <Text style={styles.inlineActionText}>Intentar de nuevo</Text>
            </TouchableOpacity>
          </>
        )}
        {doc.id === browserFallbackDocId ? browserFallback : null}
      </View>
    );
  };

  const addDocument = (
    <View style={styles.section}>
      <Text style={styles.sectionLabel}>{verifiedCount ? 'Agregar otro documento' : 'Elige tu documento'}</Text>
      {!hasCountryAttempt ? (
        <TouchableOpacity style={styles.optionCard} onPress={handleStartDidit} disabled={isBusy} accessibilityRole="button">
          <View style={styles.documentIcon}>
            {isLaunchingDidit
              ? <ActivityIndicator color={colors.primaryDark} />
              : <Icon name="credit-card" size={18} color={colors.primaryDark} />}
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.optionTitle}>
              {phoneCountryName ? `Documento de ${phoneCountryName}` : 'Documento del país de tu teléfono'}
            </Text>
            <Text style={styles.optionBody}>Recompensas, recargar y retirar, y cuentas locales donde se acepte.</Text>
          </View>
          <Icon name="chevron-right" size={20} color={colors.textSecondary} />
        </TouchableOpacity>
      ) : null}
      {!hasCountryAttempt ? browserFallback : null}
      <TouchableOpacity style={styles.optionCard} onPress={openOtherDocument} disabled={isBusy} accessibilityRole="button">
        <View style={styles.documentIcon}>
          <Icon name="book" size={18} color={colors.primaryDark} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.optionTitle}>Pasaporte o documento de otro país</Text>
          <Text style={styles.optionBody}>Recompensas y cuentas locales en Colombia, México, Brasil y Argentina.</Text>
        </View>
        <Icon name="chevron-right" size={20} color={colors.textSecondary} />
      </TouchableOpacity>
      <Text style={styles.hint}>Tus datos deben coincidir en todos tus documentos: mismo nombre y fecha de nacimiento.</Text>
      {/* Consent for Confío's own use of the selfie (Didit's screen covers only Didit). */}
      <Text style={styles.consent}>
        Al continuar, aceptas que usemos tu selfie para verificar tu identidad y, más adelante, para confirmar con
        tu rostro que eres tú.{' '}
        <Text style={styles.consentLink} accessibilityRole="link"
          onPress={() => navigation.navigate('LegalDocument', { docType: 'privacy' })}>
          Política de privacidad
        </Text>
      </Text>
    </View>
  );

  const howItWorks = (
    <View style={styles.section}>
      <Text style={styles.sectionLabel}>Cómo funciona</Text>
      <View style={styles.card}>
        {[
          'Abres una verificación segura dentro de la app.',
          'Tomas una foto de tu documento y una selfie. Son unos 2 minutos.',
          'Te avisamos cuando termine la revisión.',
        ].map((text, index) => (
          <View key={text} style={[styles.stepRow, index > 0 && styles.divided]}>
            <View style={styles.stepNumber}>
              <Text style={styles.stepNumberText}>{index + 1}</Text>
            </View>
            <Text style={styles.stepText}>{text}</Text>
          </View>
        ))}
      </View>
    </View>
  );

  // Business accounts: the company's verification, as before.
  const businessView = (
    <View style={styles.card}>
      <View style={styles.documentHeader}>
        <View style={styles.documentIcon}>
          <Icon name="briefcase" size={18} color={colors.primaryDark} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.documentTitle}>{activeAccount?.business?.name || 'Tu negocio'}</Text>
          <Text style={styles.documentSubtitle}>Verificación del negocio (KYB)</Text>
        </View>
        <StatusPill status={effectiveStatus} />
      </View>
      <Text style={styles.note}>
        {effectiveStatus === 'verified'
          ? 'Tu negocio está verificado.'
          : effectiveStatus === 'rejected'
            ? effectiveDetail || 'No pudimos verificar tu negocio. Contacta a soporte si necesitas ayuda antes de volver a intentarlo.'
          : effectiveStatus === 'pending'
            ? effectiveDetail || 'Continúa la verificación de tu negocio o espera el resultado de la revisión.'
            : 'Completa los datos de la empresa, sus documentos y la verificación de sus representantes y propietarios.'}
      </Text>
      {effectiveStatus !== 'verified' ? (
        <Button
          title={effectiveStatus === 'pending' ? 'Continuar verificación del negocio' : 'Verificar mi negocio'}
          onPress={handleStartDidit}
          loading={isLaunchingDidit}
          disabled={isBusy}
          icon={<Icon name="arrow-up-right" size={18} color={colors.white} />}
        />
      ) : null}
    </View>
  );

  // An older server without the documents list: the single status, unchanged.
  const fallbackView = (
    <View style={styles.card}>
      <View style={styles.documentHeader}>
        <View style={styles.documentIcon}>
          <Icon name="shield" size={18} color={colors.primaryDark} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.documentTitle}>Tu identidad</Text>
          <Text style={styles.documentSubtitle}>Verificación con Didit</Text>
        </View>
        <StatusPill status={effectiveStatus} />
      </View>
      {effectiveStatus === 'rejected' ? (
        <Text style={styles.note}>{effectiveDetail || 'No pudimos verificar tu identidad. Inténtalo de nuevo o contacta a soporte.'}</Text>
      ) : null}
      {effectiveStatus !== 'verified' ? (
        <Button
          title={effectiveStatus === 'pending' ? 'Enviar otra verificación' : 'Verificar con Didit'}
          onPress={handleStartDidit}
          loading={isLaunchingDidit}
          disabled={isBusy}
          icon={<Icon name="arrow-up-right" size={18} color={colors.white} />}
        />
      ) : null}
      {effectiveStatus !== 'verified' ? browserFallback : null}
    </View>
  );

  return (
    <View style={styles.container}>
      <Header title="Verificación" navigation={navigation} backgroundColor={colors.heroField} isLight={true} />
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refreshStatuses} tintColor={colors.primaryDark} />}
      >
        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={dismissBanner}
            autoHideMs={banner.variant === 'success' ? 3500 : undefined}
            style={{ marginBottom: 0 }}
          />
        )}

        {isBusinessAccount ? businessView : documents === null && !documentsQuery.loading ? fallbackView : (
          <>
            {summary}
            {featureGuide}
            {list.length ? (
              <View style={styles.section}>
                <Text style={styles.sectionLabel}>Tus documentos</Text>
                {list.map(renderDocument)}
              </View>
            ) : null}
            {addDocument}
            {howItWorks}
          </>
        )}

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Pagos locales</Text>
          <TouchableOpacity
            style={styles.optionCard}
            onPress={() => navigation.navigate('LocalLimitIncrease')}
            accessibilityRole="button"
          >
            <View style={styles.documentIcon}>
              <Icon name="trending-up" size={18} color={colors.primaryDark} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.optionTitle}>Aumentar mi límite de pagos locales</Text>
              <Text style={styles.optionBody}>
                {isBusinessAccount
                  ? 'El límite inicial de pagos locales para empresas es de US$100,000 al mes. Para superar ese monto, solicita una revisión con soporte.'
                  : 'El límite inicial de pagos locales es de US$10,000 al mes. Para superar ese monto, completa una verificación del origen de tus fondos y solicita un límite mayor.'}
              </Text>
            </View>
            <Icon name="chevron-right" size={20} color={colors.textSecondary} />
          </TouchableOpacity>
          <Text style={styles.hint}>Este límite mensual solo aplica a pagos locales. No aplica a Recargar ni Retirar.</Text>
        </View>

        {isInitialLoading ? (
          <View style={styles.loadingBlock}>
            <ActivityIndicator color={colors.primaryDark} />
            <Text style={styles.loadingText}>Cargando tu verificación…</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surfaceMuted },
  scrollView: { flex: 1 },
  content: { padding: 20, gap: 22, paddingBottom: 40 },

  summaryCard: {
    backgroundColor: colors.surface, borderRadius: 22, padding: 20, borderWidth: 1, borderColor: colors.primaryLight,
    gap: 10,
  },
  summaryTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  summaryIcon: {
    width: 44, height: 44, borderRadius: 14, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  summaryTitle: { fontSize: 22, fontWeight: '800', color: colors.dark, marginTop: 4 },
  summaryBody: { fontSize: 15, lineHeight: 22, color: colors.textSecondary },

  section: { gap: 10 },
  sectionLabel: {
    fontSize: 13, fontWeight: '800', letterSpacing: 0.6, textTransform: 'uppercase', color: colors.textSecondary,
    marginLeft: 4,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: 18, padding: 16, borderWidth: 1, borderColor: colors.border, gap: 12,
  },
  divided: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 12 },

  guideRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  featureIcon: {
    width: 36, height: 36, borderRadius: 11, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  featureTitle: { fontSize: 15, fontWeight: '800', color: colors.dark },
  featureBody: { fontSize: 13, lineHeight: 19, color: colors.textSecondary, marginTop: 2 },

  documentHeader: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  documentIcon: {
    width: 40, height: 40, borderRadius: 12, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  documentTitle: { fontSize: 16, fontWeight: '800', color: colors.dark },
  documentSubtitle: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  statusPill: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  statusPillText: { fontSize: 12, fontWeight: '700' },

  capabilityList: { gap: 10, backgroundColor: colors.surfaceMuted, borderRadius: 14, padding: 12 },
  capabilityRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  capabilityMark: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  markYes: { backgroundColor: colors.primaryDark },
  markNo: { backgroundColor: colors.border },
  capabilityTitle: { fontSize: 14, fontWeight: '700', color: colors.dark },
  capabilityDetail: { fontSize: 13, lineHeight: 18, color: colors.textSecondary, marginTop: 1 },
  muted: { color: colors.textSecondary },

  note: { fontSize: 14, lineHeight: 20, color: colors.textSecondary },
  inlineAction: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' },
  inlineActionText: { fontSize: 14, fontWeight: '700', color: colors.primaryDark },

  optionCard: {
    backgroundColor: colors.surface, borderRadius: 18, padding: 16, borderWidth: 1, borderColor: colors.primaryLight,
    flexDirection: 'row', alignItems: 'center', gap: 12,
  },
  optionTitle: { fontSize: 15, fontWeight: '800', color: colors.dark },
  optionBody: { fontSize: 13, lineHeight: 19, color: colors.textSecondary, marginTop: 2 },
  hint: { fontSize: 13, lineHeight: 19, color: colors.textSecondary, marginHorizontal: 4 },
  consent: { fontSize: 12, lineHeight: 17, color: colors.textSecondary, marginHorizontal: 4, marginTop: 10 },
  consentLink: { color: colors.primaryDark, fontWeight: '600' },

  stepRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  stepNumber: {
    width: 26, height: 26, borderRadius: 13, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  stepText: { flex: 1, fontSize: 14, lineHeight: 20, color: colors.dark },

  loadingBlock: { paddingVertical: 24, alignItems: 'center', gap: 10 },
  loadingText: { color: colors.textSecondary, fontSize: 14 },
});

export default VerificationScreen;
