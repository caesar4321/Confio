import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../../config/theme';

interface SuccessHeroProps {
  /** "¡Pago realizado!" / "¡Enviado con éxito!" */
  title: string;
  /** "$25.00 cUSD" — the one big number */
  amount: string;
  /** One quiet line: "Pagado en Bodega Central" */
  hint?: string;
  /** Instrument tint (e.g. colors.secondary for CONFIO); default emerald */
  tint?: string;
  /** Amount color; defaults to primaryDark (pair it with tint) */
  amountColor?: string;
  /** Optional slot under the hint (badges, notices) */
  children?: React.ReactNode;
}

/**
 * The app-wide success moment (grammar from ConvertAhorro/RetirarAhorro,
 * the version the owner picked as reference): white page, emerald check
 * circle, short title, ONE big amount in primaryDark, one hint line.
 * Everything else on a success screen is secondary to these four things.
 */
export const SuccessHero: React.FC<SuccessHeroProps> = ({ title, amount, hint, tint, amountColor, children }) => (
  <View style={styles.wrap}>
    <View style={[styles.icon, tint ? { backgroundColor: tint } : null]}>
      <Icon name="check" size={40} color={colors.white} />
    </View>
    <Text style={styles.title} accessibilityRole="header">{title}</Text>
    <Text style={[styles.amount, amountColor ? { color: amountColor } : null]}>{amount}</Text>
    {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    {children}
  </View>
);

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    paddingTop: 48,
    paddingBottom: 28,
    paddingHorizontal: 32,
    backgroundColor: colors.background,
  },
  icon: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text.primary,
    textAlign: 'center',
  },
  amount: {
    fontSize: 42,
    fontWeight: 'bold',
    color: colors.primaryDark,
    marginTop: 10,
  },
  hint: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: 10,
    lineHeight: 20,
  },
});
