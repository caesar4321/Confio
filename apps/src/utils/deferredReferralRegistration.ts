type DeferredReferralLink = {
  type: 'referral' | 'influencer' | 'achievement' | 'deeplink';
  payload: string;
  timestamp: number;
  metadata?: Record<string, string | undefined>;
};

type MutationResult = {
  data?: {
    setReferrer?: {
      success?: boolean;
      error?: string | null;
      message?: string | null;
    } | null;
  } | null;
  errors?: ReadonlyArray<{ message: string }>;
};

type RegistrationDependencies = {
  init: () => Promise<void>;
  getDeferredLink: () => Promise<DeferredReferralLink | null>;
  clearDeferredLink: (expected: DeferredReferralLink) => Promise<boolean>;
  setReferrer: (variables: {
    referrerIdentifier: string;
    attributionData: string;
  }) => Promise<MutationResult>;
  alert: (title: string, message: string) => void;
};

export type DeferredReferralResult = 'none' | 'success' | 'retry' | 'discarded';

export const formatDeferredReferralError = (rawMessage?: string): string => {
  if (!rawMessage) return 'Error al registrar referidor';
  if (/rate limit/i.test(rawMessage)) {
    const minutes = rawMessage.match(/(\d+)\s*minutes?/i)?.[1];
    if (minutes) {
      return `Has intentado demasiadas veces. Por favor espera ${minutes} minuto${minutes === '1' ? '' : 's'} antes de intentar nuevamente.`;
    }
    return 'Has intentado demasiadas veces. Por favor espera unos minutos antes de intentar nuevamente.';
  }
  if (/suspicious/i.test(rawMessage)) {
    return 'Detectamos actividad inusual. Por favor contacta a soporte.';
  }
  return rawMessage;
};

export const consumeDeferredReferral = async (
  dependencies: RegistrationDependencies,
): Promise<DeferredReferralResult> => {
  await dependencies.init();
  const link = await dependencies.getDeferredLink();
  if (!link || link.type !== 'referral') return 'none';

  const result = await dependencies.setReferrer({
    referrerIdentifier: link.payload,
    attributionData: JSON.stringify({
      ...(link.metadata || {}),
      referral_code: link.payload,
      attach_method: 'deferred_link',
    }),
  });

  const graphQLError = result.errors?.[0]?.message;
  if (graphQLError) {
    const friendly = formatDeferredReferralError(graphQLError);
    if (/rate limit/i.test(graphQLError) || /demasiadas veces/i.test(friendly)) {
      dependencies.alert('Aviso', friendly);
      return 'retry';
    }
    if (/suspicious/i.test(graphQLError) || /unusual|inusual/i.test(friendly)) {
      await dependencies.clearDeferredLink(link);
      return 'discarded';
    }
    const permanent =
      /own referrer|not found|invalid|already/i.test(graphQLError) ||
      /propio referidor|no encontrado|inválido|ya tienes|registrado/i.test(friendly);
    if (permanent) {
      await dependencies.clearDeferredLink(link);
      dependencies.alert('Aviso', friendly);
      return 'discarded';
    }
    dependencies.alert('Aviso', friendly);
    return 'retry';
  }

  if (result.data?.setReferrer?.success) {
    await dependencies.clearDeferredLink(link);
    return 'success';
  }

  const rawError = String(
    result.data?.setReferrer?.error ||
    result.data?.setReferrer?.message ||
    'Error desconocido',
  );
  const friendly = formatDeferredReferralError(rawError);
  const suppressed = /already|ya registraste|ya tienes|suspicious|unusual|inusual/i.test(rawError);
  if (suppressed) {
    await dependencies.clearDeferredLink(link);
    return 'discarded';
  }

  const retryable = /rate limit|demasiadas veces|intenta de nuevo|conexión|connection/i.test(rawError);
  if (!retryable) await dependencies.clearDeferredLink(link);
  dependencies.alert('Aviso', friendly);
  return retryable ? 'retry' : 'discarded';
};
