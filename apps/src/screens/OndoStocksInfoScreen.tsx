import React from 'react';
import {
  Alert,
  Image,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import {useNavigation} from '@react-navigation/native';
import {NativeStackNavigationProp} from '@react-navigation/native-stack';
import {gql, useQuery} from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import {Header} from '../navigation/Header';
import {colors} from '../config/theme';
import {MainStackParamList} from '../types/navigation';
import {useSavingsPortfolio} from '../hooks/useSavingsPortfolio';
import {useGmMarket} from '../hooks/useGmMarket';
import {useCurrency} from '../hooks/useCurrency';
import {useAuthReady} from '../contexts/AuthContext';
import {TickerLogo} from '../components/TickerLogo';
import OndoLogo from '../assets/png/Ondo.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

const ONDO_STOCKS_URL = 'https://ondo.finance/ondo-stocks';

// The trade fee is an env-driven server setting (CUSD_PLUS_GM_TRADE_FEE_BPS),
// and the router's on-chain stockFeeBps is authoritative above even that — so
// this screen must never carry the number as a literal. This eligible-only
// query also returns the privacy-safe community rollup from the same snapshot
// as the Home market-value figure.
const STOCK_INFO = gql`
  query OndoStocksInfoFee {
    cusdPlusConvertParams {
      gmTradeFeeBps
      stockRouterAddress
    }
    gmCommunity {
      valueUsd
      holderWallets
      positions
      updatedAt
      assets {
        symbol
        ticker
        name
        valueUsd
        sharePct
      }
    }
  }
`;

// Account-specific and deliberately separate from the shared market/config
// query. During an account switch, useAuthReady pauses this network-only read
// until the JWT points at the new account, preventing a cached old address
// from becoming the destination of the proof link.
const STOCK_WALLET_ADDRESS = gql`
  query OndoStocksWalletAddress {
    stockWalletAddress
  }
`;

// 30 bps -> "0,30". Comma is the decimal mark in the app's Spanish copy.
const formatFeePercent = (bps: number) =>
  (bps / 100).toFixed(2).replace('.', ',');

// Same shape as ProtectedSavingsScreen's, so the two hero pills that quote a
// Home stat read identically. null stays "—": unknown is not zero.
const formatWhole = (n: number | null | undefined, sep: string) => {
  if (n == null) return '—';
  const r = Math.round(n);
  try {
    return new Intl.NumberFormat('en-US', {maximumFractionDigits: 0})
      .format(r)
      .replace(/,/g, sep);
  } catch {
    return `${r}`;
  }
};

type NavProp = NativeStackNavigationProp<MainStackParamList>;

type CommunityStock = {
  symbol: string;
  ticker: string;
  name: string;
  valueUsd: number;
  sharePct: number;
};

const ExplanationRow = ({
  icon,
  title,
  body,
}: {
  icon: string;
  title: string;
  body: string;
}) => (
  <View style={styles.explanationRow}>
    <View style={styles.explanationIcon}>
      <Icon name={icon} size={16} color={colors.primaryDark} />
    </View>
    <View style={styles.explanationCopy}>
      <Text style={styles.explanationTitle}>{title}</Text>
      <Text style={styles.explanationBody}>{body}</Text>
    </View>
  </View>
);

export const OndoStocksInfoScreen = () => {
  const navigation = useNavigation<NavProp>();
  const {stocks} = useSavingsPortfolio();
  const isAuthReady = useAuthReady();

  // Hooks must run before the eligibility return below, so both are wired
  // here and simply skip themselves when the product is off.
  const {currency} = useCurrency();
  const {stocks: marketAssets} = useGmMarket(stocks.enabled);
  const {data: feeData} = useQuery(STOCK_INFO, {
    skip: !stocks.enabled,
    fetchPolicy: 'cache-and-network',
    pollInterval: 300_000,
  });
  const {data: walletData} = useQuery(STOCK_WALLET_ADDRESS, {
    skip: !stocks.enabled || !isAuthReady,
    fetchPolicy: 'network-only',
  });
  // useGmMarket returns an EMPTY list while loading and on upstream failure
  // (its documented honesty rule — never a fake price), so a bare
  // `marketAssets.length` would render "0 acciones" as if that were a fact.
  // Treat unknown as unknown and drop to the countless phrasing instead.
  const assetCount = marketAssets.length;
  const catalogLabel =
    assetCount > 0
      ? `${assetCount} acciones y ETFs`
      : 'Acciones y ETFs de EE.UU.';

  // gm_tvl refuses to publish a partial scan, so this field is legitimately
  // null whenever the aggregation or a held-asset price failed. Render the
  // pill only when there is a real figure — a "US$0 en acciones" pill would
  // read as "nobody is invested" rather than "we don't know right now".
  const stocksTvl: number | null | undefined = feeData?.gmCommunity?.valueUsd;
  const stocksTvlLabel =
    stocksTvl != null
      ? formatWhole(stocksTvl, currency.thousandsSeparator)
      : null;
  const communityStocks: CommunityStock[] = feeData?.gmCommunity?.assets ?? [];
  const communityHolderWallets: number | null | undefined =
    feeData?.gmCommunity?.holderWallets;
  const communityPositions: number | null | undefined =
    feeData?.gmCommunity?.positions;
  const communityUpdatedAt: string | null | undefined =
    feeData?.gmCommunity?.updatedAt;
  const communityUpdatedLabel = (() => {
    if (!communityUpdatedAt) return null;
    const date = new Date(communityUpdatedAt);
    if (!Number.isFinite(date.getTime())) return null;
    return date.toLocaleString('es-419', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  })();
  const marketByTicker = new Map(
    marketAssets.map(asset => [asset.ticker, asset]),
  );
  const formatUsd = (value: number) => {
    const rendered = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
    return rendered
      .replace(/,/g, '__THOUSANDS__')
      .replace('.', currency.decimalSeparator)
      .replace(/__THOUSANDS__/g, currency.thousandsSeparator);
  };

  // Same rule for the fee: assert a rate only once the server has told us one.
  const feeBps: number | null | undefined =
    feeData?.cusdPlusConvertParams?.gmTradeFeeBps;
  const feeSentence =
    feeBps == null
      ? 'Confío cobra una comisión sobre cada compra y venta completada.'
      : feeBps === 0
        ? 'Por ahora Confío no cobra comisión por operar.'
        : `Confío cobra un ${formatFeePercent(feeBps)}% sobre cada compra y venta completada.`;

  const userBscAddress: string | null = isAuthReady
    ? (walletData?.stockWalletAddress ?? null)
    : null;
  const routerAddress: string | null =
    feeData?.cusdPlusConvertParams?.stockRouterAddress ?? null;
  const isBscAddress = (address: string | null): address is string =>
    Boolean(address && /^0x[0-9a-fA-F]{40}$/.test(address));

  const openMyStocks = () => {
    if (!isBscAddress(userBscAddress)) return;
    Linking.openURL(
      `https://bscscan.com/tokenholdings?a=${userBscAddress}`,
    ).catch(() => {});
  };

  const explainConfioSystem = () => {
    if (!isBscAddress(routerAddress)) return;
    Alert.alert(
      'Cómo funciona Confío',
      'Esta página pública muestra el sistema que Confío utiliza para procesar compras y ventas. Contiene información técnica y operaciones de todos los usuarios, pero no revela sus identidades.',
      [
        {text: 'Cancelar', style: 'cancel'},
        {
          text: 'Continuar',
          onPress: () =>
            Linking.openURL(
              `https://bscscan.com/address/${routerAddress}#code`,
            ).catch(() => {}),
        },
      ],
    );
  };

  // The navigation entry points are hidden for blocked jurisdictions, but
  // the screen also fails closed for stale navigation state and deep links.
  if (!stocks.enabled) {
    return (
      <View style={styles.unavailableContainer}>
        <Icon name="globe" size={34} color={colors.text.light} />
        <Text style={styles.unavailableTitle}>Acciones no disponibles</Text>
        <Text style={styles.unavailableBody}>
          Este producto solo aparece en jurisdicciones habilitadas.
        </Text>
        <TouchableOpacity
          onPress={() => navigation.goBack()}
          style={styles.backButton}
          accessibilityRole="button"
          accessibilityLabel="Volver">
          <Text style={styles.backButtonText}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const openOndo = () => Linking.openURL(ONDO_STOCKS_URL).catch(() => {});

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Acciones de EE.UU."
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <View style={styles.heroLogos}>
            <Image
              source={cUSDPlusLogo}
              style={styles.heroLogo}
              resizeMode="contain"
            />
            <View style={styles.heroArrow}>
              <Icon name="arrow-right" size={18} color={colors.primaryDark} />
            </View>
            <Image
              source={OndoLogo}
              style={styles.heroLogo}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Tu ahorro, conectado al mercado</Text>
          <Text style={styles.heroSubtitle}>
            Obtén exposición económica a acciones y ETFs de EE.UU. mediante
            tokens de Ondo Stocks, directamente desde Confío.
          </Text>
          <View style={styles.heroPills}>
            <View style={styles.heroPill}>
              <Icon name="bar-chart-2" size={14} color={colors.primary} />
              <Text style={styles.heroPillText}>{catalogLabel}</Text>
            </View>
            <View style={styles.heroPill}>
              <Icon name="clock" size={14} color={colors.primary} />
              {/* Not "24/5": weekend trading is a PER-ASSET flag (GmAssetType
                  .offHours), so a blanket claim here contradicted both the
                  schema and this screen's own hours copy two sections down. */}
              <Text style={styles.heroPillText}>
                24/5 y algunos fines de semana
              </Text>
            </View>
            {stocksTvlLabel && (
              <View style={styles.heroPill}>
                <Icon name="trending-up" size={14} color={colors.primary} />
                <Text style={styles.heroPillText}>
                  US${stocksTvlLabel} en acciones
                </Text>
              </View>
            )}
          </View>
        </View>

        {communityStocks.length > 0 && (
          <View style={styles.section}>
            <View style={styles.sectionHeadingRow}>
              <Icon name="pie-chart" size={20} color={colors.primary} />
              <Text style={styles.sectionTitleInline}>
                En qué invierte la comunidad
              </Text>
            </View>
            <Text style={styles.communityIntro}>
              Posiciones actuales agregadas, valoradas con los precios de
              mercado de Ondo. No mostramos identidades ni billeteras.
            </Text>
            {communityStocks.map(asset => {
              const marketAsset = marketByTicker.get(asset.ticker);
              return (
                <View key={asset.symbol} style={styles.communityRow}>
                  <TickerLogo
                    ticker={asset.ticker}
                    color={marketAsset?.color ?? '#334155'}
                    logoUrl={marketAsset?.logoUrl}
                    size={38}
                  />
                  <View style={styles.communityIdentity}>
                    <Text style={styles.communityTicker}>{asset.ticker}</Text>
                    <Text style={styles.communityName} numberOfLines={1}>
                      {asset.name || marketAsset?.name || asset.ticker}
                    </Text>
                  </View>
                  <View style={styles.communityValueColumn}>
                    <Text style={styles.communityValue}>
                      US${formatUsd(asset.valueUsd)}
                    </Text>
                    <Text style={styles.communityShare}>
                      {asset.sharePct
                        .toFixed(1)
                        .replace('.', currency.decimalSeparator)}
                      %
                    </Text>
                  </View>
                </View>
              );
            })}
            <Text style={styles.communityFootnote}>
              {communityHolderWallets != null
                ? `${communityHolderWallets} ${communityHolderWallets === 1 ? 'cartera con posiciones' : 'carteras con posiciones'} · `
                : ''}
              {communityPositions != null
                ? `${communityPositions} ${communityPositions === 1 ? 'posición' : 'posiciones'} · `
                : ''}
              {communityUpdatedLabel
                ? `Datos al ${communityUpdatedLabel}.`
                : 'Datos de la última valoración disponible.'}
            </Text>
          </View>
        )}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>¿Cómo funciona?</Text>
          <ExplanationRow
            icon="search"
            title="1. Elige una acción o ETF"
            body="Consulta el precio, el cambio del día y el horario disponible antes de invertir."
          />
          <ExplanationRow
            icon="repeat"
            title="2. Invierte desde tu ahorro"
            body="La compra usa cUSD+. Antes de confirmar ves la cotización y el costo de operación."
          />
          <ExplanationRow
            icon="corner-down-left"
            title="3. Vende de vuelta a cUSD+"
            body="Cuando vendes, el resultado vuelve a tu ahorro y queda disponible dentro de Confío."
          />
        </View>

        <View style={styles.section}>
          <View style={styles.sectionHeadingRow}>
            <Icon name="shield" size={20} color={colors.primary} />
            <Text style={styles.sectionTitleInline}>
              Qué representa el token
            </Text>
          </View>
          <Text style={styles.sectionBody}>
            Los tokens de Ondo Stocks están diseñados para estar totalmente
            respaldados por las acciones, ETFs y efectivo correspondientes, y
            brindar una exposición económica similar al activo subyacente.
          </Text>
          <View style={styles.clarityCard}>
            <Icon name="info" size={18} color={colors.violet} />
            <Text style={styles.clarityText}>
              No significa que la acción tradicional quede registrada
              directamente a tu nombre. Mantienes un token emitido por la
              plataforma Ondo Stocks que sigue el rendimiento del activo.
            </Text>
          </View>
          <Text style={styles.sectionBody}>
            Los dividendos se reflejan mediante reinversión automática, netos de
            las retenciones aplicables, en vez de pagarse como efectivo por
            separado.
          </Text>
        </View>

        <View style={styles.section}>
          <View style={styles.sectionHeadingRow}>
            <Icon name="eye" size={20} color={colors.primary} />
            <Text style={styles.sectionTitleInline}>
              Costos y horarios claros
            </Text>
          </View>
          <Text style={styles.sectionBody}>
            {feeSentence} La app te muestra la cotización y el resultado
            estimado antes de confirmar.
          </Text>
          <Text style={styles.sectionBody}>
            La mayoría de los activos opera de forma continua durante la semana.
            Algunos también pueden estar disponibles en fines de semana, según
            el activo y las condiciones del servicio. Una operación puede
            pausarse temporalmente por mercado, eventos corporativos o controles
            de riesgo.
          </Text>
        </View>

        {(isBscAddress(userBscAddress) || isBscAddress(routerAddress)) && (
          <View style={styles.section}>
            <View style={styles.sectionHeadingRow}>
              <Icon name="check-circle" size={20} color={colors.primary} />
              <Text style={styles.sectionTitleInline}>
                Comprueba tus acciones
              </Text>
            </View>
            <Text style={styles.sectionBody}>
              Las acciones digitales que compras quedan guardadas directamente
              en tu cuenta. Puedes comprobarlas públicamente cuando quieras.
            </Text>
            <Text style={styles.proofExplanation}>
              Confío realiza tus compras y ventas mediante un sistema público y
              verificable. Tus acciones permanecen en tu cuenta, no en Confío.
            </Text>
            {/* Same chip grammar as the cUSD+ reserve links: these are proof
                links, not actions — the visual weight of a full-width button
                made them compete with "Explorar acciones". */}
            <View style={styles.linksRow}>
              {isBscAddress(userBscAddress) && (
                <TouchableOpacity
                  style={styles.linkButton}
                  onPress={openMyStocks}
                  activeOpacity={0.8}
                  accessibilityRole="link"
                  accessibilityLabel="Ver mis acciones">
                  <Icon name="external-link" size={13} color={colors.primary} />
                  <Text style={styles.linkText}>Ver mis acciones</Text>
                </TouchableOpacity>
              )}
              {isBscAddress(routerAddress) && (
                <TouchableOpacity
                  style={styles.linkButton}
                  onPress={explainConfioSystem}
                  activeOpacity={0.8}
                  accessibilityRole="button"
                  accessibilityLabel="Ver cómo funciona Confío">
                  <Icon name="external-link" size={13} color={colors.primary} />
                  <Text style={styles.linkText}>Ver cómo funciona Confío</Text>
                </TouchableOpacity>
              )}
            </View>
            <Text style={styles.proofWarning}>
              BscScan también puede mostrar tokens desconocidos enviados por
              terceros. Confío solo reconoce las acciones que aparecen dentro de
              la app.
            </Text>
          </View>
        )}

        <View style={styles.riskSection}>
          <View style={styles.sectionHeadingRow}>
            <Icon name="alert-triangle" size={20} color={colors.warning.icon} />
            <Text style={styles.riskTitle}>Antes de invertir</Text>
          </View>
          <Text style={styles.riskBody}>
            El valor puede subir o bajar y podrías perder dinero. También
            existen riesgos del emisor, custodia, liquidez, tecnología y
            regulación. La disponibilidad depende de tu jurisdicción y de los
            proveedores del servicio. Esto no es asesoría financiera.
          </Text>
        </View>

        <View style={styles.partnerRow}>
          <Text style={styles.partnerText}>En alianza con</Text>
          <Image source={OndoLogo} style={styles.partnerLogo} />
          <Text style={styles.partnerBrand}>Ondo Finance</Text>
        </View>

        <View style={styles.officialLinkRow}>
          <TouchableOpacity
            style={styles.linkButton}
            onPress={openOndo}
            activeOpacity={0.8}
            accessibilityRole="link"
            accessibilityLabel="Más información oficial sobre Ondo Stocks">
            <Icon name="external-link" size={13} color={colors.primary} />
            <Text style={styles.linkText}>
              Información oficial de Ondo Stocks
            </Text>
          </TouchableOpacity>
        </View>

        <View style={styles.ctaSection}>
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() => navigation.navigate('StocksList')}
            activeOpacity={0.9}
            accessibilityRole="button"
            accessibilityLabel="Explorar acciones">
            <Icon name="trending-up" size={20} color={colors.white} />
            <Text style={styles.ctaText}>Explorar acciones</Text>
          </TouchableOpacity>
          {!stocks.buyEnabled && (
            <Text style={styles.ctaHint}>
              Puedes conocer el catálogo ahora. Las compras se habilitarán
              cuando el servicio esté listo para tu cuenta.
            </Text>
          )}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  // Layout grammar is shared with ProtectedSavingsScreen (the cUSD+
  // explanation page): white page, neutral-filled borderless section cards
  // laid out with a 16pt gutter, emerald-soft chips for external proof links
  // and a single pill CTA. The two pages are siblings in the same product
  // story, so they must not read as two different apps.
  container: {flex: 1, backgroundColor: colors.white},
  scroll: {flex: 1},
  scrollContent: {paddingBottom: 32},
  unavailableContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.white,
    paddingHorizontal: 32,
  },
  unavailableTitle: {
    marginTop: 12,
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  unavailableBody: {
    marginTop: 6,
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
    color: colors.text.secondary,
  },
  backButton: {marginTop: 18, paddingHorizontal: 20, paddingVertical: 10},
  backButtonText: {color: colors.primary, fontWeight: '700'},
  hero: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  heroLogos: {flexDirection: 'row', alignItems: 'center'},
  heroLogo: {width: 56, height: 56, borderRadius: 14},
  heroArrow: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 10,
    backgroundColor: colors.primarySoft,
  },
  heroTitle: {
    marginTop: 12,
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    color: colors.dark,
  },
  heroSubtitle: {
    marginTop: 6,
    paddingHorizontal: 16,
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
    color: colors.text.secondary,
  },
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 8,
    marginTop: 14,
  },
  heroPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.primarySoft,
  },
  heroPillText: {fontSize: 12, fontWeight: '700', color: colors.primary},
  section: {
    marginHorizontal: 16,
    marginBottom: 16,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 12,
  },
  sectionHeadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
  },
  sectionTitleInline: {
    flex: 1,
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  sectionBody: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.text.primary,
    marginBottom: 8,
  },
  communityIntro: {
    marginBottom: 4,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
  },
  communityRow: {
    minHeight: 58,
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  communityIdentity: {flex: 1, marginLeft: 11, marginRight: 8},
  communityTicker: {fontSize: 14, fontWeight: '700', color: colors.dark},
  communityName: {marginTop: 2, fontSize: 12, color: colors.text.secondary},
  communityValueColumn: {alignItems: 'flex-end'},
  communityValue: {fontSize: 13, fontWeight: '700', color: colors.text.primary},
  communityShare: {marginTop: 2, fontSize: 11, color: colors.text.light},
  communityFootnote: {
    marginTop: 10,
    fontSize: 11,
    lineHeight: 16,
    color: colors.text.light,
  },
  explanationRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  explanationIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  explanationCopy: {flex: 1, marginLeft: 11},
  explanationTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.dark,
  },
  explanationBody: {
    marginTop: 3,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
  },
  // White-on-neutral inset, same construction as the cUSD+ yield split and
  // trust-chain cards; the violet icon keeps this the page's one "read this
  // twice" note without inventing a second card style.
  clarityCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginBottom: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    backgroundColor: colors.white,
  },
  clarityText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.primary,
  },
  proofExplanation: {
    marginBottom: 8,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
  },
  linksRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
  },
  linkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: colors.primarySoft,
  },
  linkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  proofWarning: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 17,
    fontStyle: 'italic',
    color: colors.text.secondary,
  },
  riskSection: {
    marginHorizontal: 16,
    marginBottom: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.warning.border,
    padding: 16,
    backgroundColor: '#FFFBEB',
  },
  riskTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  riskBody: {fontSize: 13, lineHeight: 20, color: colors.text.primary},
  partnerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 2,
    marginBottom: 10,
  },
  partnerText: {fontSize: 12, color: colors.text.light},
  partnerLogo: {width: 15, height: 15, borderRadius: 4},
  partnerBrand: {fontSize: 12, fontWeight: '700', color: colors.text.secondary},
  officialLinkRow: {alignItems: 'center', marginBottom: 20},
  ctaSection: {
    marginHorizontal: 16,
    marginBottom: 24,
    alignItems: 'center',
  },
  ctaButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 999,
    backgroundColor: colors.primary,
  },
  ctaText: {fontSize: 15, fontWeight: '700', color: colors.white},
  ctaHint: {
    marginTop: 10,
    paddingHorizontal: 12,
    fontSize: 12,
    lineHeight: 18,
    textAlign: 'center',
    color: colors.text.secondary,
  },
});
