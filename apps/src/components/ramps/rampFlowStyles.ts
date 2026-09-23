import { StyleSheet } from 'react-native';
import { colors } from '../../config/theme';

/**
 * The Recarga/Retiro visual language (SellScreen/TopUpScreen), shared by the
 * local-money flows so Enviar/Recibir por cuenta local read as the same family.
 * Values are copied verbatim from SellScreen's stylesheet — change them there
 * first, then here, never here alone.
 */
export const rampFlowStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: 60 },

  bannerCard: {
    flexDirection: 'row', alignItems: 'flex-start', backgroundColor: '#f0fdf4', borderRadius: 16,
    padding: 16, marginHorizontal: 22, marginBottom: 20, gap: 12, borderWidth: 1, borderColor: '#bbf7d0',
    shadowColor: colors.primaryDark, shadowOpacity: 0.08, shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  bannerIconWrap: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(5,150,105,0.12)', alignItems: 'center',
    justifyContent: 'center', marginTop: 2,
  },
  bannerCopy: { flex: 1 },
  bannerTitle: { fontSize: 14, fontWeight: '700', color: colors.primaryDark, marginBottom: 4 },
  bannerText: { fontSize: 13, lineHeight: 19, color: colors.textFlat },
  historyPill: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'center', backgroundColor: colors.surface,
    borderWidth: 1, borderColor: '#bbf7d0', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8,
  },
  historyPillText: { fontSize: 12, fontWeight: '700', color: colors.primary },

  loadingCard: {
    backgroundColor: colors.surface, borderRadius: 20, padding: 28, marginHorizontal: 22, alignItems: 'center',
    gap: 12, shadowColor: colors.text.primary, shadowOpacity: 0.06, shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 }, elevation: 2,
  },
  loadingText: { color: colors.textSecondary, fontSize: 14, textAlign: 'center', lineHeight: 20 },

  section: { marginBottom: 24, paddingHorizontal: 22 },
  sectionHeader: {
    flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12, gap: 12,
  },
  sectionHeaderContent: { flex: 1 },

  inputCard: {
    backgroundColor: colors.surface, borderRadius: 20, padding: 20, borderWidth: 1, borderColor: colors.primaryLight,
    shadowColor: colors.text.primary, shadowOpacity: 0.06, shadowRadius: 16, shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  inputLabel: { fontSize: 13, fontWeight: '600', color: colors.textSecondary, marginBottom: 8 },
  amountInputRow: {
    flexDirection: 'row', alignItems: 'center', borderRadius: 14, borderWidth: 1.5, borderColor: 'transparent',
    paddingHorizontal: 2, paddingVertical: 2, marginHorizontal: -2,
  },
  amountInputRowFocused: {
    borderColor: colors.primary, backgroundColor: '#f0fdf4', borderRadius: 14, paddingHorizontal: 8,
  },
  amountInput: { flex: 1, fontSize: 32, fontWeight: '700', color: colors.dark, paddingVertical: 4 },
  currencyBadge: {
    backgroundColor: colors.primaryLight, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5, marginLeft: 8,
  },
  currencyBadgeText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark, letterSpacing: 0.4 },
  helperText: { color: colors.textSecondary, lineHeight: 18, marginTop: 10, fontSize: 13 },
  limitText: { color: colors.textSecondary, lineHeight: 18, marginTop: 8, fontSize: 12 },
  errorText: { color: colors.danger, lineHeight: 18, marginTop: 8, fontSize: 12, fontWeight: '600' },

  methodList: { gap: 10 },
  methodCard: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 16, flexDirection: 'row', alignItems: 'center',
    gap: 14, borderWidth: 1.5, borderColor: '#eef2f7', shadowColor: colors.text.primary, shadowOpacity: 0.05,
    shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2,
  },
  methodCardSelected: {
    backgroundColor: colors.primaryDark, borderColor: colors.primaryDark, borderWidth: 2,
    shadowColor: colors.primaryDark, shadowOpacity: 0.22, shadowRadius: 14, shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  methodCopy: { flex: 1, gap: 2 },
  methodIcon: {
    width: 40, height: 40, borderRadius: 12, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  methodIconSelected: { backgroundColor: 'rgba(255,255,255,0.2)' },
  methodTitle: { fontSize: 15, fontWeight: '700', color: colors.dark },
  methodTitleSelected: { color: colors.white },
  methodText: { color: colors.textSecondary, lineHeight: 18, fontSize: 13 },
  methodTextSelected: { color: 'rgba(255,255,255,0.75)' },

  radioOuter: {
    width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.border, alignItems: 'center',
    justifyContent: 'center',
  },
  radioOuterSelected: { borderColor: 'rgba(255,255,255,0.5)', backgroundColor: 'rgba(255,255,255,0.18)' },
  radioOuterChecked: { borderColor: colors.primaryDark, backgroundColor: colors.primaryDark },
  radioInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.white },

  addButton: {
    flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.primarySoft, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, borderWidth: 1, borderColor: '#a7f3d0',
  },
  addButtonText: { color: colors.primaryDark, fontWeight: '700', fontSize: 13 },

  emptyCard: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 20, gap: 8, alignItems: 'center',
    shadowColor: colors.text.primary, shadowOpacity: 0.04, shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  },
  emptyTitle: { fontWeight: '700', color: colors.dark, textAlign: 'center' },
  emptyText: { color: colors.textSecondary, lineHeight: 18, textAlign: 'center', fontSize: 13 },
  emptyStateCard: {
    backgroundColor: colors.surface, borderRadius: 22, padding: 22, marginHorizontal: 22, marginTop: 4,
    alignItems: 'center', borderWidth: 1, borderColor: colors.primaryLight, shadowColor: colors.text.primary,
    shadowOpacity: 0.06, shadowRadius: 16, shadowOffset: { width: 0, height: 6 }, elevation: 3,
  },
  emptyStateIconWrap: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center', marginBottom: 14,
  },
  emptyStateTitle: { fontWeight: '800', color: colors.dark, textAlign: 'center', fontSize: 20 },
  emptyStateText: { color: colors.textSecondary, lineHeight: 22, textAlign: 'center', fontSize: 15, marginTop: 10 },
  primaryActionButton: {
    marginTop: 18, minWidth: 180, paddingHorizontal: 18, paddingVertical: 14, borderRadius: 16,
    backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center',
  },
  primaryActionButtonText: { color: colors.surface, fontWeight: '800', fontSize: 15 },

  savedCard: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 16, flexDirection: 'row',
    justifyContent: 'space-between', alignItems: 'center', gap: 14, marginTop: 8, borderWidth: 1,
    borderColor: '#eef2f7', shadowColor: colors.text.primary, shadowOpacity: 0.05, shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 }, elevation: 2,
  },
  savedCardSelected: {
    backgroundColor: colors.primaryLight, borderColor: '#a7f3d0', shadowColor: colors.primary, shadowOpacity: 0.12,
  },
  savedCopy: { flex: 1, gap: 4 },
  savedTitle: { fontWeight: '700', color: colors.dark },
  savedText: { color: colors.textSecondary, fontSize: 13 },

  quoteCard: {
    backgroundColor: '#f0fdf8', borderRadius: 20, padding: 20, gap: 10, borderWidth: 1.5,
    borderColor: colors.primary, shadowColor: colors.primaryDark, shadowOpacity: 0.14, shadowRadius: 20,
    shadowOffset: { width: 0, height: 8 }, elevation: 4,
  },
  quoteHeadline: { fontSize: 34, fontWeight: '800', color: colors.primaryDark, lineHeight: 40 },
  quoteHeadlineCompact: { fontSize: 28, lineHeight: 34 },
  quoteEyebrow: {
    fontSize: 11, fontWeight: '700', letterSpacing: 1.2, textTransform: 'uppercase', color: colors.primaryDark,
  },
  quoteRate: { color: colors.textSecondary, fontSize: 13, lineHeight: 20 },
  quoteDivider: { height: 1, backgroundColor: colors.border, marginVertical: 4 },
  quoteRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, paddingVertical: 4,
  },
  quoteLabel: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, flex: 1 },
  quoteValue: {
    color: colors.dark, fontWeight: '700', fontSize: 14, lineHeight: 20, flex: 1, textAlign: 'right',
  },
  quoteFinalDivider: { height: 1, backgroundColor: colors.primary, opacity: 0.35, marginTop: 2 },
  quoteFinalRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 18, paddingVertical: 4,
  },
  quoteFinalLabel: { flex: 1, color: colors.primaryDark, fontSize: 15, lineHeight: 22, fontWeight: '800' },
  quoteFinalValue: {
    flex: 1, color: colors.primaryDark, fontSize: 18, lineHeight: 24, fontWeight: '800', textAlign: 'right',
  },
  disclaimerPill: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.primarySoft, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 8, gap: 8, marginTop: 4, borderWidth: 1, borderColor: '#a7f3d0',
  },
  quoteNote: { color: colors.primaryDark, lineHeight: 18, fontSize: 12, flex: 1 },
  emptyQuote: { alignItems: 'center', gap: 8, paddingVertical: 8 },

  reviewCard: {
    backgroundColor: colors.surface, borderRadius: 20, padding: 20, marginHorizontal: 22, gap: 14, borderWidth: 1,
    borderColor: colors.primaryLight, borderLeftWidth: 5, borderLeftColor: colors.primary,
    shadowColor: colors.primary, shadowOpacity: 0.12, shadowRadius: 16, shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  settlementNotice: { flexDirection: 'row', alignItems: 'flex-start', gap: 6, marginBottom: 12 },
  settlementNoticeText: { flex: 1, fontSize: 12, color: colors.textSecondary, lineHeight: 17 },
  reviewTitle: { fontSize: 18, fontWeight: '700', color: colors.dark },
  reviewRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingVertical: 6 },
  reviewLabel: { flex: 0.95, color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  reviewValue: {
    flex: 1.15, color: colors.dark, fontWeight: '600', fontSize: 14, lineHeight: 20, textAlign: 'right',
  },
  reviewValueHighlight: {
    flex: 1.15, color: colors.primary, fontWeight: '800', fontSize: 16, lineHeight: 22, textAlign: 'right',
  },

  // ── Local-money additions, built from the same tokens ──
  textInput: { flex: 1, fontSize: 17, fontWeight: '600', color: colors.dark, paddingVertical: 10 },
  recipientCard: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white,
    borderRadius: 16, padding: 16, marginTop: 12,
  },
  verifiedCard: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#f0fdf4', borderRadius: 16, padding: 16,
    marginTop: 12, borderWidth: 1, borderColor: '#bbf7d0',
  },
  initials: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primaryLight, alignItems: 'center',
    justifyContent: 'center',
  },
  initialsText: { fontSize: 15, fontWeight: '800', color: colors.primaryDark },
  verifiedPill: {
    flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: colors.primaryLight, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 4, alignSelf: 'flex-start', marginTop: 4,
  },
  verifiedPillText: { fontSize: 12, fontWeight: '700', color: colors.successText },
  warningCard: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 10, backgroundColor: colors.warning.background,
    borderRadius: 14, padding: 14, marginTop: 12, borderWidth: 1, borderColor: colors.warning.border,
  },
  warningTitle: { fontSize: 14, fontWeight: '700', color: colors.warning.text },
  warningText: { fontSize: 13, lineHeight: 18, color: colors.warning.text, marginTop: 2 },
  warningLink: { fontSize: 13, fontWeight: '700', color: colors.warning.text, textDecorationLine: 'underline', marginTop: 6 },
  checkboxRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginTop: 12, minHeight: 44 },
  checkbox: {
    width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: colors.borderMedium, alignItems: 'center',
    justifyContent: 'center', marginTop: 1,
  },
  checkboxChecked: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  checkboxText: { flex: 1, fontSize: 14, lineHeight: 20, color: colors.text.primary },
  detailValue: { fontSize: 22, fontWeight: '800', color: colors.dark, letterSpacing: 0.5, marginTop: 2 },
  detailMeta: { fontSize: 13, color: colors.textSecondary, lineHeight: 19, marginTop: 6 },
  buttonRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  smallPrimary: {
    flex: 1, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', borderRadius: 14,
    paddingVertical: 13, backgroundColor: colors.primaryDark,
  },
  smallPrimaryText: { color: colors.white, fontSize: 15, fontWeight: '800' },
  scannedRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 14,
    paddingVertical: 12, paddingHorizontal: 14, backgroundColor: '#f0fdf4',
  },
  scannedText: { flex: 1, color: colors.successText, fontSize: 15, fontWeight: '700' },
  scannedAgain: { color: colors.primaryDark, fontSize: 14, fontWeight: '700' },
  smallGhost: {
    flex: 1, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', borderRadius: 14,
    paddingVertical: 13, borderWidth: 1, borderColor: colors.primaryLight, backgroundColor: '#f0fdf4',
  },
  smallGhostText: { color: colors.successText, fontSize: 15, fontWeight: '700' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  chip: {
    borderRadius: 999, paddingHorizontal: 14, paddingVertical: 9, borderWidth: 1, borderColor: '#eef2f7',
    backgroundColor: colors.surface,
  },
  chipSelected: { backgroundColor: colors.primaryLight, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.dark },
  chipTextSelected: { color: colors.successText },
  progressTrack: { height: 6, borderRadius: 3, backgroundColor: colors.surfaceMuted, overflow: 'hidden', marginTop: 10 },
  progressFill: { height: 6, borderRadius: 3, backgroundColor: colors.primary },
  timelineRow: { flexDirection: 'row', gap: 12 },
  timelineRail: { alignItems: 'center' },
  timelineDot: {
    width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center', borderWidth: 2,
    borderColor: colors.border, backgroundColor: colors.white,
  },
  timelineDotDone: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  timelineDotActive: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  timelineDotInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary },
  timelineLine: { width: 2, flex: 1, minHeight: 22, backgroundColor: colors.border, marginVertical: 4 },
  timelineLineDone: { backgroundColor: colors.primary },
  timelineLabel: { fontSize: 15, fontWeight: '600', color: colors.dark, paddingTop: 2, paddingBottom: 16 },
  timelineLabelTodo: { color: colors.textTertiary },
  timelineLabelActive: { fontWeight: '800' },
  reference: { fontSize: 12, color: colors.textTertiary, marginTop: 4 },
});
