import React from 'react';
import { View, Text, StyleSheet, Modal, ScrollView, Linking, Alert, useWindowDimensions } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button } from './common/Button';
import { colors } from '../config/theme';

// Google's own storage manager (support.google.com/googleone/answer/6374270).
export const GOOGLE_STORAGE_MANAGER_URL = 'https://one.google.com/storage/management';

interface DriveStorageFullModalProps {
    visible: boolean;
    onRetry: () => void;
    onClose: () => void;
}

const STEPS: { icon: string; text: string }[] = [
    { icon: 'trash-can-outline', text: 'Vacía la papelera y el spam de Gmail y de Google Drive. Es lo más rápido.' },
    { icon: 'image-remove', text: 'Borra fotos, videos o correos con archivos grandes que ya no necesites.' },
    { icon: 'clock-outline', text: 'Espera unos minutos: Google tarda un poco en actualizar tu espacio disponible.' },
];

export const DriveStorageFullModal: React.FC<DriveStorageFullModalProps> = ({ visible, onRetry, onClose }) => {
    const insets = useSafeAreaInsets();
    const { height } = useWindowDimensions();
    const modalMaxHeight = Math.max(360, height - insets.top - insets.bottom - 32);

    const openStorageManager = async () => {
        try {
            await Linking.openURL(GOOGLE_STORAGE_MANAGER_URL);
        } catch (_error) {
            Alert.alert(
                'No pudimos abrir Google',
                'Abre one.google.com/storage/management en tu navegador para liberar espacio.',
            );
        }
    };

    return (
        <Modal
            animationType="fade"
            transparent={true}
            visible={visible}
            statusBarTranslucent
            onRequestClose={onClose}
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
                            <Icon name="cloud-alert" size={44} color={colors.warning.text} />
                        </View>

                        <Text style={styles.modalTitle} accessibilityRole="header">
                            Tu almacenamiento de Google está lleno
                        </Text>

                        <Text style={styles.modalText}>
                            Tu respaldo necesita muy poco espacio, pero tu cuenta de Google ya no tiene espacio disponible. Libera un poco y vuelve a intentarlo.
                        </Text>

                        <View style={styles.infoContainer}>
                            <Icon name="information-outline" size={18} color={colors.primaryDark} />
                            <Text style={styles.infoText}>
                                Tu espacio de Google se comparte entre Gmail, Google Fotos, Google Drive y los respaldos de WhatsApp.
                            </Text>
                        </View>

                        <View style={styles.bulletPoints}>
                            {STEPS.map(step => (
                                <View key={step.icon} style={styles.bulletRow}>
                                    <View style={styles.bulletChip}>
                                        <Icon name={step.icon} size={18} color={colors.primaryDark} />
                                    </View>
                                    <Text style={styles.bulletText}>{step.text}</Text>
                                </View>
                            ))}
                        </View>
                    </ScrollView>

                    <View style={styles.footer}>
                        <Button title="Liberar espacio en Google" onPress={openStorageManager} />
                        <Button
                            title="Ya liberé espacio, reintentar"
                            variant="secondary"
                            onPress={onRetry}
                            style={styles.footerButton}
                        />
                        <Button title="Cerrar" variant="ghost" onPress={onClose} style={styles.footerButton} />
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
        backgroundColor: colors.warning.background,
        borderWidth: 1,
        borderColor: colors.warning.border,
        borderRadius: 44,
        height: 88,
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
        marginBottom: 16,
        textAlign: 'center',
        color: colors.gray700,
        fontSize: 15,
        lineHeight: 23,
    },
    infoContainer: {
        flexDirection: 'row',
        backgroundColor: colors.primarySoft,
        padding: 12,
        borderRadius: 12,
        marginBottom: 20,
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
    bulletPoints: {
        width: '100%',
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
