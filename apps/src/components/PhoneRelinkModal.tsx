import React, { useEffect, useRef } from 'react';
import { AccessibilityInfo, View, Text, StyleSheet, Modal, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { Button } from './common/Button';
import { colors } from '../config/theme';
import { useModalCardLayout } from '../hooks/useModalCardLayout';
import type { PhoneRelinkPrompt } from '../hooks/usePhoneRelinkPrompt';

type AccountSummary = { email?: string | null; username?: string | null };

interface PhoneRelinkModalProps {
    /** Visible while set; stays presented from the first question until the relink flow settles. */
    prompt: PhoneRelinkPrompt | null;
    phoneLabel: string;
    /** The signed-in account the number will move to, when the profile has loaded. */
    currentAccount?: AccountSummary | null;
    /** Always receives the id of the prompt the pressed button was rendered for. */
    onAnswer: (promptId: number, approved: boolean) => void;
}

const REPLACED_NOTICE = 'Las cuentas vinculadas a este número cambiaron. Revísalas antes de confirmar.';
const RETRY_NOTICE = 'No pudimos confirmar el cambio. Revisa tu conexión e intenta de nuevo.';

// Identifiers wrap instead of truncating: the user must be able to read every
// character that tells two accounts apart before approving the move.
const AccountRow: React.FC<{ account: AccountSummary | null; highlighted?: boolean }> = ({ account, highlighted }) => (
    <View style={[styles.accountRow, highlighted && styles.accountRowHighlighted]}>
        <View style={[styles.avatar, highlighted && styles.avatarHighlighted]}>
            <Icon name="account-outline" size={20} color={highlighted ? colors.primaryDark : colors.gray700} />
        </View>
        <View style={styles.accountText}>
            {account ? (
                <>
                    <Text style={styles.accountEmail}>{account.email || 'Correo no disponible'}</Text>
                    {!!account.username && <Text style={styles.accountUsername}>{`@${account.username}`}</Text>}
                </>
            ) : (
                <Text style={styles.accountEmail}>La cuenta con la que iniciaste sesión</Text>
            )}
        </View>
    </View>
);

export const PhoneRelinkModal: React.FC<PhoneRelinkModalProps> = ({
    prompt,
    phoneLabel,
    currentAccount,
    onAnswer,
}) => {
    const layout = useModalCardLayout();
    const scrollRef = useRef<ScrollView>(null);
    const accounts = prompt?.confirmation.accounts ?? [];
    const plural = accounts.length > 1;
    const phase = prompt?.phase ?? 'ask';
    const confirming = phase === 'confirming';
    const replaced = !!prompt?.replaced;
    const promptId = prompt?.id;
    const answer = (approved: boolean) => {
        if (promptId !== undefined) onAnswer(promptId, approved);
    };

    // A new question can arrive while the modal is already presented: bring
    // changed accounts back into view and tell screen-reader users what changed.
    useEffect(() => {
        if (promptId === undefined) return;
        if (phase === 'ask' && replaced) {
            scrollRef.current?.scrollTo({ y: 0, animated: false });
            AccessibilityInfo.announceForAccessibility(REPLACED_NOTICE);
        } else if (phase === 'retry') {
            AccessibilityInfo.announceForAccessibility(RETRY_NOTICE);
        }
    }, [promptId, phase, replaced]);

    const footer = (
        <View
            testID="phone-relink-footer"
            style={styles.footer}
            onLayout={layout.onFooterLayout}
        >
            {phase === 'retry' && (
                <View style={[styles.notice, styles.noticeError, styles.retryNotice]} accessibilityLiveRegion="polite">
                    <Icon name="wifi-off" size={18} color={colors.error.text} />
                    <Text style={[styles.noticeText, { color: colors.error.text }]}>{RETRY_NOTICE}</Text>
                </View>
            )}
            <Button
                title={phase === 'retry' ? 'Reintentar' : 'Confirmar cambio'}
                onPress={() => answer(true)}
                loading={confirming}
            />
            <Button
                title="Cancelar"
                variant="ghost"
                onPress={() => answer(false)}
                disabled={confirming}
                style={styles.footerButton}
            />
        </View>
    );

    return (
        <Modal
            animationType="fade"
            transparent={true}
            visible={!!prompt}
            statusBarTranslucent
            onRequestClose={() => {
                if (!confirming) answer(false);
            }}
        >
            <View
                style={[
                    styles.centeredView,
                    { paddingTop: layout.paddingTop, paddingBottom: layout.paddingBottom },
                ]}
            >
                <View style={[styles.modalView, { maxHeight: layout.maxHeight }]}>
                    <ScrollView
                        ref={scrollRef}
                        style={styles.scrollView}
                        bounces={false}
                        showsVerticalScrollIndicator
                        nestedScrollEnabled
                    >
                        <View style={styles.modalContent}>
                            <View style={styles.iconContainer}>
                                <Icon name="cellphone-link" size={40} color={colors.primaryDark} />
                            </View>

                            <Text style={styles.modalTitle} accessibilityRole="header">
                                ¿Mover este número a tu cuenta?
                            </Text>

                            <Text style={styles.modalText}>
                                <Text style={styles.phone}>{phoneLabel}</Text>
                                {plural ? ' ya está vinculado a otras cuentas.' : ' ya está vinculado a otra cuenta.'}
                            </Text>

                            {replaced && (
                                <View style={[styles.notice, styles.noticeWarning, styles.replacedNotice]}>
                                    <Icon name="alert-outline" size={18} color={colors.warning.text} />
                                    <Text style={[styles.noticeText, { color: colors.warning.text }]}>{REPLACED_NOTICE}</Text>
                                </View>
                            )}

                            <Text style={styles.sectionLabel}>Ahora está en</Text>
                            <View style={styles.accountList}>
                                {accounts.map((account, index) => (
                                    <AccountRow key={`${account.email}-${account.username}-${index}`} account={account} />
                                ))}
                            </View>

                            <View style={styles.arrowChip}>
                                <Icon name="arrow-down" size={18} color={colors.primaryDark} />
                            </View>

                            <Text style={styles.sectionLabel}>Pasará a</Text>
                            <AccountRow account={currentAccount ?? null} highlighted />

                            <View style={styles.infoContainer}>
                                <Icon name="shield-check-outline" size={18} color={colors.primaryDark} />
                                <Text style={styles.infoText}>
                                    {`Los fondos y el historial se quedan en ${plural ? 'las cuentas anteriores' : 'la cuenta anterior'}. Solo cambia la cuenta a la que pertenece este número.`}
                                </Text>
                            </View>
                        </View>
                        {layout.inlineFooter && footer}
                    </ScrollView>

                    {!layout.inlineFooter && footer}
                </View>
            </View>
        </Modal>
    );
};

const styles = StyleSheet.create({
    centeredView: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.6)',
        padding: 20,
    },
    modalView: {
        width: '100%',
        maxWidth: 360,
        backgroundColor: colors.background,
        borderRadius: 24,
        shadowColor: colors.dark,
        shadowOffset: {
            width: 0,
            height: 8,
        },
        shadowOpacity: 0.18,
        shadowRadius: 24,
        elevation: 8,
        overflow: 'hidden',
    },
    scrollView: {
        flexShrink: 1,
    },
    modalContent: {
        padding: 24,
        alignItems: 'center',
        paddingBottom: 16,
    },
    iconContainer: {
        marginBottom: 16,
        backgroundColor: colors.primarySoft,
        borderWidth: 1,
        borderColor: colors.primaryLight,
        borderRadius: 40,
        height: 80,
        width: 80,
        alignItems: 'center',
        justifyContent: 'center',
    },
    modalTitle: {
        fontSize: 22,
        fontWeight: '800',
        color: colors.dark,
        marginBottom: 8,
        textAlign: 'center',
    },
    modalText: {
        marginBottom: 20,
        textAlign: 'center',
        color: colors.gray700,
        fontSize: 15,
        lineHeight: 22,
    },
    phone: {
        fontWeight: '700',
        color: colors.dark,
    },
    notice: {
        width: '100%',
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
        padding: 12,
        borderRadius: 12,
        borderWidth: 1,
    },
    noticeWarning: {
        backgroundColor: colors.warning.background,
        borderColor: colors.warning.border,
    },
    noticeError: {
        backgroundColor: colors.error.background,
        borderColor: colors.error.border,
    },
    noticeText: {
        flex: 1,
        fontSize: 13,
        lineHeight: 18,
    },
    replacedNotice: {
        marginBottom: 16,
    },
    retryNotice: {
        marginBottom: 12,
    },
    sectionLabel: {
        alignSelf: 'flex-start',
        fontSize: 12,
        fontWeight: '700',
        letterSpacing: 0.5,
        textTransform: 'uppercase',
        color: colors.text.secondary,
        marginBottom: 8,
    },
    accountList: {
        width: '100%',
        gap: 8,
    },
    accountRow: {
        width: '100%',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        padding: 12,
        borderRadius: 14,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.background,
    },
    accountRowHighlighted: {
        borderColor: colors.primary,
        backgroundColor: colors.primarySoft,
    },
    avatar: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: colors.neutralDark,
        alignItems: 'center',
        justifyContent: 'center',
    },
    avatarHighlighted: {
        backgroundColor: colors.primaryLight,
    },
    accountText: {
        flex: 1,
    },
    accountEmail: {
        fontSize: 15,
        fontWeight: '600',
        color: colors.dark,
    },
    accountUsername: {
        marginTop: 2,
        fontSize: 13,
        color: colors.text.secondary,
    },
    arrowChip: {
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: colors.primarySoft,
        alignItems: 'center',
        justifyContent: 'center',
        marginVertical: 12,
    },
    infoContainer: {
        flexDirection: 'row',
        backgroundColor: colors.primarySoft,
        padding: 12,
        borderRadius: 12,
        marginTop: 20,
        width: '100%',
        alignItems: 'flex-start',
        gap: 10,
    },
    infoText: {
        flex: 1,
        color: colors.gray700,
        fontSize: 13,
        lineHeight: 18,
    },
    footer: {
        width: '100%',
        paddingHorizontal: 24,
        paddingTop: 12,
        paddingBottom: 20,
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.border,
        backgroundColor: colors.background,
    },
    footerButton: {
        marginTop: 10,
    },
});
