
import React from 'react';
import { View, Text, StyleSheet, Modal, ScrollView, useWindowDimensions } from 'react-native';
// MaterialCommunityIcons for the cloud-lock mark (linked in iOS Info.plist)
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button } from './common/Button';
import { colors } from '../config/theme';

interface BackupConsentModalProps {
    visible: boolean;
    onContinue: () => void;
    onCancel: () => void;
}

export const BackupConsentModal: React.FC<BackupConsentModalProps> = ({ visible, onContinue, onCancel }) => {
    const insets = useSafeAreaInsets();
    const { height } = useWindowDimensions();
    const modalMaxHeight = Math.max(360, height - insets.top - insets.bottom - 32);

    return (
        <Modal
            animationType="fade"
            transparent={true}
            visible={visible}
            statusBarTranslucent
            // By passing an empty function, Android back button will not dismiss this mandatory modal
            onRequestClose={() => { }}
        >
            <View
                style={[
                    styles.centeredView,
                    {
                        paddingTop: Math.max(insets.top, 16),
                        paddingBottom: Math.max(insets.bottom, 16),
                    },
                ]}
            >
                <View style={[styles.modalView, { maxHeight: modalMaxHeight }]}>
                    <ScrollView
                        style={styles.scrollView}
                        contentContainerStyle={styles.modalContent}
                        bounces={false}
                        showsVerticalScrollIndicator
                        nestedScrollEnabled
                    >
                        <View style={styles.iconContainer}>
                            <Icon name="cloud-lock-outline" size={44} color={colors.primaryDark} />
                        </View>

                        <Text style={styles.modalTitle} accessibilityRole="header">Protege tu billetera</Text>

                        <Text style={styles.modalText}>
                            Para que <Text style={styles.bold}>nunca pierdas tu dinero</Text>, Confío guardará una copia cifrada de tu llave maestra en tu <Text style={styles.bold}>Google Drive personal</Text>.
                        </Text>

                        <View style={styles.bulletPoints}>
                            <View style={styles.bulletRow}>
                                <View style={styles.bulletChip}>
                                    <Icon name="lock-outline" size={16} color={colors.primaryDark} />
                                </View>
                                <Text style={styles.bulletText}>Solo tú tienes acceso, con tu cuenta de Google.</Text>
                            </View>
                            <View style={styles.bulletRow}>
                                <View style={styles.bulletChip}>
                                    <Icon name="backup-restore" size={16} color={colors.primaryDark} />
                                </View>
                                <Text style={styles.bulletText}>Recupera tu billetera automáticamente si cambias de teléfono.</Text>
                            </View>
                            <View style={styles.bulletRow}>
                                <View style={styles.bulletChip}>
                                    <Icon name="shield-check-outline" size={16} color={colors.primaryDark} />
                                </View>
                                <Text style={styles.bulletText}>Sin contraseñas extra que recordar.</Text>
                            </View>
                        </View>

                        <View style={styles.warningContainer}>
                            <Icon name="information-outline" size={18} color={colors.warning.icon} />
                            <Text style={styles.warningText}>
                                Verás una solicitud de permiso para acceder a "configuración de la aplicación". Es 100% privado.
                            </Text>
                        </View>
                    </ScrollView>

                    <View style={styles.footer}>
                        <Button
                            title="Proteger y continuar"
                            onPress={onContinue}
                        />
                    </View>
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
        borderRadius: 44,
        height: 88, // Fixed size to prevent shift
        width: 88,
        alignItems: 'center',
        justifyContent: 'center',
    },
    modalTitle: {
        fontSize: 22,
        fontWeight: '800',
        color: colors.dark,
        marginBottom: 12,
        textAlign: 'center',
    },
    modalText: {
        marginBottom: 20,
        textAlign: 'center',
        color: colors.gray700,
        fontSize: 15,
        lineHeight: 23,
    },
    bold: {
        fontWeight: '700',
        color: colors.dark,
    },
    bulletPoints: {
        width: '100%',
        marginBottom: 20,
        gap: 12,
    },
    bulletRow: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
    },
    bulletChip: {
        width: 32,
        height: 32,
        borderRadius: 10,
        backgroundColor: colors.primarySoft,
        alignItems: 'center',
        justifyContent: 'center',
    },
    bulletText: {
        flex: 1,
        fontSize: 14,
        color: colors.gray700,
        lineHeight: 20,
        paddingTop: 6, // optically centers single lines against the 32px chip
    },
    warningContainer: {
        flexDirection: 'row',
        backgroundColor: colors.warning.background,
        borderWidth: 1,
        borderColor: colors.warning.border,
        padding: 12,
        borderRadius: 12,
        marginBottom: 8,
        width: '100%',
        alignItems: 'flex-start',
        gap: 10,
    },
    warningText: {
        flex: 1,
        color: colors.warning.text,
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
});
