import React from 'react';
import {
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
import Icon from 'react-native-vector-icons/Feather';
import {Header} from '../navigation/Header';
import {colors} from '../config/theme';
import {MainStackParamList} from '../types/navigation';
import {useSavingsPortfolio} from '../hooks/useSavingsPortfolio';
import OndoLogo from '../assets/png/Ondo.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

const ONDO_STOCKS_URL = 'https://ondo.finance/ondo-stocks';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

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
      <Icon name={icon} size={17} color={colors.primaryDark} />
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
              <Icon name="bar-chart-2" size={14} color={colors.primaryDark} />
              <Text style={styles.heroPillText}>400+ activos</Text>
            </View>
            <View style={styles.heroPill}>
              <Icon name="clock" size={14} color={colors.primaryDark} />
              <Text style={styles.heroPillText}>Mercado 24/5</Text>
            </View>
          </View>
        </View>

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
            <Icon name="shield" size={20} color={colors.primaryDark} />
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
            <Icon name="eye" size={20} color={colors.primaryDark} />
            <Text style={styles.sectionTitleInline}>
              Costos y horarios claros
            </Text>
          </View>
          <Text style={styles.sectionBody}>
            Confío cobra un 0,30% en cada compra y venta completada. La app te
            muestra la cotización y el resultado estimado antes de confirmar.
          </Text>
          <Text style={styles.sectionBody}>
            La mayoría de los activos opera de forma continua durante la semana.
            Algunos también pueden estar disponibles en fines de semana, según
            el activo y las condiciones del servicio. Una operación puede
            pausarse temporalmente por mercado, eventos corporativos o controles
            de riesgo.
          </Text>
        </View>

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

        <TouchableOpacity
          style={styles.officialLink}
          onPress={openOndo}
          activeOpacity={0.8}
          accessibilityRole="link"
          accessibilityLabel="Más información oficial sobre Ondo Stocks">
          <Text style={styles.officialLinkText}>
            Información oficial de Ondo Stocks
          </Text>
          <Icon name="external-link" size={15} color={colors.primaryDark} />
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.ctaButton}
          onPress={() => navigation.navigate('StocksList')}
          activeOpacity={0.9}
          accessibilityRole="button"
          accessibilityLabel="Explorar acciones">
          <Icon name="trending-up" size={19} color={colors.white} />
          <Text style={styles.ctaText}>Explorar acciones</Text>
        </TouchableOpacity>
        {!stocks.buyEnabled && (
          <Text style={styles.ctaHint}>
            Puedes conocer el catálogo ahora. Las compras se habilitarán cuando
            el servicio esté listo para tu cuenta.
          </Text>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: colors.neutral},
  scroll: {flex: 1},
  scrollContent: {padding: 16, paddingBottom: 40},
  unavailableContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.neutral,
    paddingHorizontal: 32,
  },
  unavailableTitle: {
    marginTop: 12,
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
  },
  unavailableBody: {
    marginTop: 6,
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
    color: colors.text.secondary,
  },
  backButton: {marginTop: 18, paddingHorizontal: 20, paddingVertical: 10},
  backButtonText: {color: colors.primaryDark, fontWeight: '700'},
  hero: {
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 20,
    paddingVertical: 24,
  },
  heroLogos: {flexDirection: 'row', alignItems: 'center'},
  heroLogo: {width: 52, height: 52, borderRadius: 14},
  heroArrow: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 12,
    backgroundColor: colors.primaryLight,
  },
  heroTitle: {
    marginTop: 16,
    fontSize: 22,
    lineHeight: 28,
    fontWeight: '800',
    textAlign: 'center',
    color: colors.text.primary,
  },
  heroSubtitle: {
    marginTop: 8,
    fontSize: 14,
    lineHeight: 21,
    textAlign: 'center',
    color: colors.text.secondary,
  },
  heroPills: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16},
  heroPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: colors.primaryLight,
  },
  heroPillText: {fontSize: 12, fontWeight: '700', color: colors.primaryDark},
  section: {
    marginTop: 12,
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: colors.text.primary,
    marginBottom: 14,
  },
  sectionHeadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    marginBottom: 10,
  },
  sectionTitleInline: {
    flex: 1,
    fontSize: 17,
    fontWeight: '800',
    color: colors.text.primary,
  },
  sectionBody: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.text.secondary,
    marginBottom: 10,
  },
  explanationRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  explanationIcon: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  explanationCopy: {flex: 1, marginLeft: 11},
  explanationTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
  },
  explanationBody: {
    marginTop: 3,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
  },
  clarityCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginBottom: 12,
    borderRadius: 12,
    padding: 12,
    backgroundColor: '#F5F3FF',
  },
  clarityText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
  },
  riskSection: {
    marginTop: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#FDE68A',
    padding: 16,
    backgroundColor: '#FFFBEB',
  },
  riskTitle: {
    flex: 1,
    fontSize: 17,
    fontWeight: '800',
    color: colors.text.primary,
  },
  riskBody: {fontSize: 13, lineHeight: 20, color: colors.text.secondary},
  partnerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    marginTop: 18,
  },
  partnerText: {fontSize: 12, color: colors.text.light},
  partnerLogo: {width: 18, height: 18, borderRadius: 4},
  partnerBrand: {fontSize: 12, fontWeight: '700', color: colors.text.secondary},
  officialLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    paddingVertical: 13,
  },
  officialLinkText: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  ctaButton: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 9,
    borderRadius: 14,
    backgroundColor: colors.primary,
  },
  ctaText: {fontSize: 16, fontWeight: '800', color: colors.white},
  ctaHint: {
    marginTop: 8,
    paddingHorizontal: 12,
    fontSize: 12,
    lineHeight: 18,
    textAlign: 'center',
    color: colors.text.light,
  },
});
