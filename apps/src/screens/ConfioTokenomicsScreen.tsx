import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { CONFIO_DOCUMENTS, DocumentLink, openConfioDocument } from '../components/ConfioNarrative';

type ConfioTokenomicsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

// Mirrors docs/tokenomics §3 (v3.1). This is the full-disclosure tier of the
// $CONFIO family: allocations, release rules and risks live here, not on
// every screen.
export const ConfioTokenomicsScreen = () => {
  const navigation = useNavigation<ConfioTokenomicsScreenNavigationProp>();
  const { selectedCountry } = useCountry();

  // Use the app's selected country for formatting, fallback to Venezuela
  const countryCode = selectedCountry?.[2] || 'VE';
  const formatWithLocale = (num: number, options = {}) =>
    formatNumber(num, countryCode, { minimumFractionDigits: 0, maximumFractionDigits: 0, ...options });

  const totalSupply = 1_000_000_000;

  const founderTokens = 893_600_000; // 89.36%
  const presaleTokens = 74_000_000; // 7.40%
  const culturalTokens = 15_000_000; // 1.50%
  const coBuilderTokens = 10_000_000; // 1.00% — carved out of the founder's original 903.6M
  const rewardsTokens = 7_400_000; // 0.74%

  const pct = (tokens: number) =>
    `${formatNumber((tokens / totalSupply) * 100, countryCode, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;

  const allocations = [
    {
      category: 'Fundador · Julian Moon',
      tokens: founderTokens,
      description: 'La asignación más grande, y la mostramos tal cual es: implica concentración de la propiedad.',
      release: '36 meses lineales desde su activación',
      color: colors.secondary,
      icon: 'user',
    },
    {
      category: 'Preventa pública',
      tokens: presaleTokens,
      description: 'Una sola curva continua de US$0,20 a US$1,30, sin fases ni cambios manuales.',
      release: 'Se reclama al salir al mercado',
      color: colors.primaryDark,
      icon: 'users',
    },
    {
      category: 'Invitación cultural',
      tokens: culturalTokens,
      description: 'Reconoce contribuciones documentadas a la comunidad de antes de que Confío tuviera escala.',
      release: '90 días lineales desde su activación',
      color: colors.offRampIcon,
      icon: 'heart',
    },
    {
      category: 'Co-builder creativa',
      tokens: coBuilderTokens,
      description: 'Salió de la asignación original del fundador. No aumentó el suministro.',
      release: '24 meses lineales desde su activación',
      color: colors.accent,
      icon: 'edit-3',
    },
    {
      category: 'Referidos y uso',
      tokens: rewardsTokens,
      description: 'Recompensas por invitar y usar Confío, según las reglas del programa vigente.',
      release: 'Se reclama al salir al mercado',
      color: colors.primaryDeep,
      icon: 'gift',
    },
  ];

  const lifecycle = ['Asignado', 'Reclamable', 'Reclamado', 'En circulación'];

  const risks = [
    {
      icon: 'pie-chart',
      title: 'Concentración',
      text: 'El fundador tiene el 89,36% del suministro. El vesting limita cuándo se libera, pero no elimina la concentración ni una posible presión de venta.',
    },
    {
      icon: 'droplet',
      title: 'Liquidez y precio',
      text: 'No se garantiza que salga al mercado ni que haya liquidez. Allí el precio lo fijan la oferta y la demanda, y puede quedar por debajo de la curva.',
    },
    {
      icon: 'unlock',
      title: 'Desbloqueo',
      text: 'Al salir al mercado, los reclamos de preventa y recompensas pueden aumentar de golpe la oferta disponible.',
    },
    {
      icon: 'code',
      title: 'Contratos inteligentes',
      text: 'Los contratos son públicos y verificados, pero pueden tener errores.',
    },
    {
      icon: 'database',
      title: 'Recompensas',
      text: 'Dependen de los registros, las firmas y los fondos que administra Confío. No son un depósito en garantía.',
    },
    {
      icon: 'slash',
      title: 'Sin derechos sobre la empresa',
      text: 'No representa acciones, deuda, dividendos ni votos garantizados. Puedes perder parte o todo su valor.',
    },
  ];

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Distribución $CONFIO"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
          <BrandFieldBackground id="tokenomicsField" fromColor={colors.secondary} toColor={colors.secondaryDark} ringCy="22%" ringR={80} ringWidth={20} />
          <View style={styles.heroInner}>
          <View style={styles.tokenIcon}>
            <Image
              source={CONFIOLogo}
              style={styles.tokenImage}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Reglas públicas, verificables</Text>
          <Text style={styles.heroSubtitle}>
            Quién tiene qué, cuándo se libera y qué riesgos hay. Sin letra chica.
          </Text>
          </View>
        </View>

        {/* Total Supply */}
        <View style={styles.section}>
          <View style={styles.supplyCard}>
            <Text style={styles.supplyLabel}>Suministro total y máximo</Text>
            <Text style={styles.supplyValue}>{formatWithLocale(totalSupply)}</Text>
            <Text style={styles.supplyUnit}>$CONFIO · BNB Smart Chain</Text>
            <Text style={styles.supplyNote}>Emitido una sola vez. Nadie puede emitir más.</Text>
            <TouchableOpacity
              accessibilityRole="link"
              style={styles.supplyLink}
              onPress={() => openConfioDocument(CONFIO_DOCUMENTS.token)}
            >
              <Text style={styles.supplyLinkText}>Ver en BscScan</Text>
              <Icon name="external-link" size={14} color={colors.secondary} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Distribution */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Cómo se reparte</Text>

          <View style={styles.stackBar}>
            {allocations.map(item => (
              <View
                key={item.category}
                style={[styles.stackSegment, { flex: item.tokens, backgroundColor: item.color }]}
              />
            ))}
          </View>

          {allocations.map(item => (
            <View key={item.category} style={styles.allocationCard}>
              <View style={styles.allocationHeader}>
                <View style={[styles.allocationIcon, { backgroundColor: item.color }]}>
                  <Icon name={item.icon} size={16} color={colors.white} />
                </View>
                <Text style={styles.allocationCategory}>{item.category}</Text>
                <Text style={[styles.allocationPercentage, { color: item.color }]}>{pct(item.tokens)}</Text>
              </View>
              <Text style={styles.allocationAmount}>{formatWithLocale(item.tokens)} CONFIO</Text>
              <Text style={styles.allocationDescription}>{item.description}</Text>
              <View style={styles.releaseRow}>
                <Icon name="clock" size={13} color={colors.text.secondary} />
                <Text style={styles.releaseText}>{item.release}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Allocation ≠ circulation */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Asignado no es lo mismo que en circulación</Text>
          <View style={styles.lifecycleCard}>
            <View style={styles.lifecycleRow}>
              {lifecycle.map((stage, index) => (
                <React.Fragment key={stage}>
                  <View style={styles.lifecycleChip}>
                    <Text style={styles.lifecycleChipText}>{stage}</Text>
                  </View>
                  {index < lifecycle.length - 1 && (
                    <Icon name="chevron-right" size={14} color={colors.secondary} />
                  )}
                </React.Fragment>
              ))}
            </View>
            <Text style={styles.lifecycleText}>
              Ningún bloque circula solo por estar asignado. La preventa y las recompensas se
              reclaman cuando $CONFIO salga al mercado, es decir, con su lanzamiento oficial en
              un exchange descentralizado (DEX), donde cualquiera puede comprar y vender sin
              intermediarios. Cada vesting empieza con su propia transacción de activación, que
              se publica en blockchain.
            </Text>
          </View>
        </View>

        {/* Risks */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Riesgos que debes conocer</Text>
          <View style={styles.riskList}>
            {risks.map(risk => (
              <View key={risk.title} style={styles.riskRow}>
                <View style={styles.riskIcon}>
                  <Icon name={risk.icon} size={16} color={colors.warning.icon} />
                </View>
                <View style={styles.riskContent}>
                  <Text style={styles.riskTitle}>{risk.title}</Text>
                  <Text style={styles.riskText}>{risk.text}</Text>
                </View>
              </View>
            ))}
          </View>
        </View>

        {/* Sources */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Verifícalo tú mismo</Text>
          <View>
            <DocumentLink label="Tokenomics completo" url={CONFIO_DOCUMENTS.tokenomics} />
            <DocumentLink label="Whitepaper de Confío" url={CONFIO_DOCUMENTS.whitepaper} />
            <DocumentLink label="Token $CONFIO en BscScan" url={CONFIO_DOCUMENTS.token} />
            <DocumentLink label="Contrato de preventa en BscScan" url={CONFIO_DOCUMENTS.presaleVault} />
            <DocumentLink label="Bóveda de vesting en BscScan" url={CONFIO_DOCUMENTS.vestingVault} />
          </View>
          <Text style={styles.sourcesNote}>
            La edición en inglés del tokenomics es la versión oficial; la versión en español es una traducción.
          </Text>
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  scrollView: {
    flex: 1,
  },
  heroSection: {
    backgroundColor: colors.secondary,
    overflow: 'hidden',
  },
  heroInner: {
    alignItems: 'center',
    paddingVertical: 32,
    paddingHorizontal: 20,
  },
  tokenIcon: {
    width: 80,
    height: 80,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  tokenImage: {
    width: 80,
    height: 80,
  },
  heroTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.white,
    marginBottom: 8,
    textAlign: 'center',
    lineHeight: 32,
  },
  heroSubtitle: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.85)',
    textAlign: 'center',
    lineHeight: 24,
  },
  section: {
    paddingHorizontal: 20,
    paddingTop: 32,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 16,
    textAlign: 'center',
  },
  supplyCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: colors.secondary,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  supplyLabel: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 8,
  },
  supplyValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.secondary,
    marginBottom: 4,
  },
  supplyUnit: {
    fontSize: 16,
    color: colors.text.secondary,
    fontWeight: '600',
  },
  supplyNote: {
    fontSize: 14,
    color: colors.dark,
    marginTop: 12,
    textAlign: 'center',
  },
  supplyLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
  },
  supplyLinkText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.secondary,
  },
  stackBar: {
    flexDirection: 'row',
    height: 14,
    borderRadius: 7,
    overflow: 'hidden',
    marginBottom: 16,
    gap: 2,
  },
  stackSegment: {
    minWidth: 3,
  },
  allocationCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 12,
  },
  allocationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  allocationIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  allocationCategory: {
    flex: 1,
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.dark,
  },
  allocationPercentage: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  allocationAmount: {
    fontSize: 13,
    color: colors.text.light,
    marginTop: 6,
    marginLeft: 42,
  },
  allocationDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
    marginTop: 6,
    marginLeft: 42,
  },
  releaseRow: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    marginTop: 10,
    marginLeft: 42,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
    backgroundColor: colors.neutralDark,
  },
  releaseText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  lifecycleCard: {
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 20,
  },
  lifecycleRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    marginBottom: 14,
  },
  lifecycleChip: {
    backgroundColor: colors.white,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
  },
  lifecycleChipText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.secondaryDark,
  },
  lifecycleText: {
    fontSize: 14,
    color: colors.dark,
    textAlign: 'center',
    lineHeight: 21,
  },
  riskList: {
    backgroundColor: colors.neutral,
    borderRadius: 16,
    padding: 16,
    gap: 16,
  },
  riskRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  riskIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.warning.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  riskContent: {
    flex: 1,
  },
  riskTitle: {
    fontSize: 15,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 2,
  },
  riskText: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  sourcesNote: {
    fontSize: 12,
    color: colors.text.light,
    lineHeight: 18,
    marginTop: 12,
    textAlign: 'center',
  },
  bottomPadding: {
    height: 40,
  },
});
