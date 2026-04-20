
import React from 'react';
import { View, Text, StyleSheet, Modal, TouchableOpacity, ScrollView, useWindowDimensions } from 'react-native';
// Use MaterialCommunityIcons for cloud-lock icon (now linked in iOS Info.plist)
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

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
                            <Icon name="cloud-lock-outline" size={64} color="#4F46E5" />
                        </View>

                        <Text style={styles.modalTitle}>Protección de Activos</Text>

                        <Text style={styles.modalText}>
                            Para asegurar que <Text style={styles.bold}>nunca pierdas tu dinero</Text>, Confío guardará una copia cifrada de tu llave maestra en tu <Text style={styles.bold}>Google Drive personal</Text>.
                        </Text>

                        <View style={styles.bulletPoints}>
                            <View style={styles.bulletRow}>
                                <Icon name="check-circle" size={20} color="#10B981" style={styles.bulletIcon} />
                                <Text style={styles.bulletText}>Solo TÚ tienes acceso con tu cuenta Google.</Text>
                            </View>
                            <View style={styles.bulletRow}>
                                <Icon name="check-circle" size={20} color="#10B981" style={styles.bulletIcon} />
                                <Text style={styles.bulletText}>Recupera tu billetera automáticamente si cambias de teléfono.</Text>
                            </View>
                            <View style={styles.bulletRow}>
                                <Icon name="shield-check" size={20} color="#10B981" style={styles.bulletIcon} />
                                <Text style={styles.bulletText}>Sin contraseñas extra que recordar.</Text>
                            </View>
                        </View>

                        <View style={styles.warningContainer}>
                            <Icon name="alert-circle-outline" size={20} color="#F59E0B" />
                            <Text style={styles.warningText}>
                                Verás una solicitud de permiso para acceder a "configuración de la aplicación". Es 100% privado.
                            </Text>
                        </View>
                    </ScrollView>

                    <View style={styles.footer}>
                        <TouchableOpacity
                            style={[styles.button, styles.buttonContinue]}
                            onPress={onContinue}
                        >
                            <Text style={styles.textStyle}>Proteger y Continuar</Text>
                        </TouchableOpacity>
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
        backgroundColor: 'white',
        borderRadius: 24,
        shadowColor: '#000',
        shadowOffset: {
            width: 0,
            height: 2,
        },
        shadowOpacity: 0.25,
        shadowRadius: 4,
        elevation: 5,
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
        backgroundColor: '#EEF2FF',
        padding: 16,
        borderRadius: 50,
        height: 96, // Fixed height to prevent shift
        width: 96,  // Fixed width to prevent shift
        alignItems: 'center',
        justifyContent: 'center',
    },
    modalTitle: {
        fontSize: 22,
        fontWeight: '800', // Extra bold
        color: '#111827',
        marginBottom: 12,
        textAlign: 'center',
    },
    modalText: {
        marginBottom: 20,
        textAlign: 'center',
        color: '#4B5563',
        fontSize: 16,
        lineHeight: 24,
    },
    bold: {
        fontWeight: '700',
        color: '#1F2937',
    },
    bulletPoints: {
        width: '100%',
        marginBottom: 20,
    },
    bulletRow: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        marginBottom: 10,
        minHeight: 40,
    },
    bulletIcon: {
        marginRight: 10,
        marginTop: 2,
    },
    bulletText: {
        flex: 1,
        fontSize: 14,
        color: '#374151',
        lineHeight: 20,
    },
    warningContainer: {
        flexDirection: 'row',
        backgroundColor: '#FFFBEB',
        padding: 12,
        borderRadius: 12,
        marginBottom: 24,
        width: '100%',
        minHeight: 60,
        alignItems: 'flex-start',
    },
    warningText: {
        flex: 1,
        marginLeft: 10,
        color: '#92400E',
        fontSize: 13,
        lineHeight: 18,
    },
    button: {
        borderRadius: 16,
        minHeight: 56, // Changed from fixed height
        paddingVertical: 12,
        paddingHorizontal: 16,
        justifyContent: 'center',
        width: '100%',
        alignItems: 'center',
    },
    buttonContinue: {
        backgroundColor: '#4F46E5', // Indigo-600
        elevation: 2,
    },
    footer: {
        width: '100%',
        paddingHorizontal: 24,
        paddingTop: 12,
        paddingBottom: 20,
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: '#E5E7EB',
        backgroundColor: '#FFFFFF',
    },
    textStyle: {
        color: 'white',
        fontWeight: 'bold',
        textAlign: 'center',
        fontSize: 16,
    },
});
