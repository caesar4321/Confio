import React from 'react';
import { Alert, Linking, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

// Shared by the $CONFIO family (Preventa · Moneda · Distribución). Copy is
// checked against docs/tokenomics (v3.1, 2026-09-23) and docs/whitepaper.
// Disclosure is layered: Preventa carries one line, Distribución carries the
// full rules and risks — do not stamp legal paragraphs on every screen.
export const CONFIO_DOCUMENTS = {
  tokenomics: 'https://github.com/caesar4321/Confio/blob/main/docs/tokenomics/README.es.md',
  whitepaper: 'https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.es.md',
  token: 'https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8',
  // Current cUSD vault since 2026-08-31 (BSC_PRESALE_VAULT_ADDRESS in .env.mainnet).
  presaleVault: 'https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code',
  vestingVault: 'https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code',
};

export const openConfioDocument = async (url: string) => {
  try {
    await Linking.openURL(url);
  } catch {
    Alert.alert('No se pudo abrir el enlace', 'Intenta de nuevo cuando tengas conexión.');
  }
};

type PillarStage = 'today' | 'next' | 'vision';

const STAGE_LABEL: Record<PillarStage, string> = {
  today: 'Hoy',
  next: 'Lo que sigue',
  vision: 'Visión',
};

// Dinero → Reputación → Acuerdos. Only Dinero is a shipped product; the
// stage chip keeps the other two honest about being direction, not features.
export const TRUST_PILLARS: Array<{
  key: string;
  icon: string;
  title: string;
  line: string;
  body: string;
  stage: PillarStage;
}> = [
  {
    key: 'dinero',
    icon: 'key',
    title: 'Dinero',
    line: 'Lo tuyo, tuyo.',
    body: 'Tus claves se crean y se usan en tu teléfono. Confío no guarda una llave maestra capaz de mover tu dinero por ti.',
    stage: 'today',
  },
  {
    key: 'reputacion',
    icon: 'user-check',
    title: 'Reputación',
    line: 'La confianza que construiste viaja contigo.',
    body: 'No queremos decidir cuánto vales. Queremos ayudarte a demostrar lo que ya construiste, aunque cambies de país o de plataforma.',
    stage: 'next',
  },
  {
    key: 'acuerdos',
    icon: 'file-text',
    title: 'Acuerdos',
    line: 'Promesas con reglas verificables.',
    body: 'Que algunos compromisos puedan cumplirse con reglas públicas, sin depender por completo de una sola institución.',
    stage: 'vision',
  },
];

/**
 * The three trust layers as a connected ladder. `compact` shows one line per
 * layer (Preventa); `full` adds the explanation (Moneda $CONFIO).
 */
export const TrustPillars = ({ variant = 'compact' }: { variant?: 'compact' | 'full' }) => (
  <View>
    {TRUST_PILLARS.map((pillar, index) => {
      const isLast = index === TRUST_PILLARS.length - 1;
      const isToday = pillar.stage === 'today';
      return (
        <View key={pillar.key} style={styles.pillarRow}>
          <View style={styles.pillarRail}>
            <View style={[styles.pillarIcon, isToday && styles.pillarIconToday]}>
              <Icon name={pillar.icon} size={18} color={isToday ? colors.white : colors.secondary} />
            </View>
            {!isLast && <View style={styles.pillarConnector} />}
          </View>
          <View style={[styles.pillarContent, !isLast && styles.pillarContentSpaced]}>
            <View style={styles.pillarTitleRow}>
              <Text style={styles.pillarTitle}>{pillar.title}</Text>
              <View style={[styles.stageChip, isToday && styles.stageChipToday]}>
                <Text style={[styles.stageChipText, isToday && styles.stageChipTextToday]}>
                  {STAGE_LABEL[pillar.stage]}
                </Text>
              </View>
            </View>
            <Text style={styles.pillarLine}>{pillar.line}</Text>
            {variant === 'full' && <Text style={styles.pillarBody}>{pillar.body}</Text>}
          </View>
        </View>
      );
    })}
  </View>
);

export const DocumentLink = ({ label, url }: { label: string; url: string }) => (
  <TouchableOpacity
    accessibilityRole="link"
    style={styles.docLink}
    onPress={() => openConfioDocument(url)}
  >
    <Text style={styles.docLinkText}>{label}</Text>
    <Icon name="external-link" size={16} color={colors.secondary} />
  </TouchableOpacity>
);

const styles = StyleSheet.create({
  pillarRow: {
    flexDirection: 'row',
  },
  pillarRail: {
    alignItems: 'center',
    width: 40,
    marginRight: 14,
  },
  pillarIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.violetLight,
    justifyContent: 'center',
    alignItems: 'center',
  },
  pillarIconToday: {
    backgroundColor: colors.secondary,
  },
  pillarConnector: {
    flex: 1,
    width: 2,
    marginVertical: 4,
    backgroundColor: colors.violetLight,
  },
  pillarContent: {
    flex: 1,
    paddingTop: 2,
  },
  pillarContentSpaced: {
    paddingBottom: 20,
  },
  pillarTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 2,
  },
  pillarTitle: {
    fontSize: 17,
    fontWeight: 'bold',
    color: colors.dark,
  },
  stageChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    backgroundColor: colors.neutralDark,
  },
  stageChipToday: {
    backgroundColor: colors.primaryLight,
  },
  stageChipText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  stageChipTextToday: {
    color: colors.primaryDark,
  },
  pillarLine: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.secondaryDark,
    lineHeight: 21,
  },
  pillarBody: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
    marginTop: 4,
  },
  docLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderColor: colors.border,
  },
  docLinkText: {
    flex: 1,
    fontSize: 15,
    fontWeight: '600',
    color: colors.secondary,
  },
});
