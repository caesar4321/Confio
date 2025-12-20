import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    TouchableOpacity,
    Platform,
    Dimensions,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import FAIcon from 'react-native-vector-icons/FontAwesome';

interface GuardarianReturnModalProps {
    visible: boolean;
    onConvert: () => void;
    onRetirar: () => void;
    onCancel: () => void;
}

const { width } = Dimensions.get('window');

const GuardarianReturnModal: React.FC<GuardarianReturnModalProps> = ({
    visible,
    onConvert,
    onRetirar,
    onCancel,
}) => {
    return (
        <Modal
            visible={visible}
            transparent
            animationType="fade"
            onRequestClose={onCancel}
            statusBarTranslucent
        >
            <View style={styles.overlay}>
                <View style={styles.modalContainer}>
                    {/* Header with Success Icon */}
                    <View style={styles.header}>
                        <View style={styles.iconContainer}>
                            <Icon name="check" size={28} color="#10B981" />
                        </View>
                        <Text style={styles.title}>¡Listo para continuar!</Text>
                        <Text style={styles.subtitle}>
                            Envía tus USDC a la dirección de Guardarian
                        </Text>
                    </View>

                    {/* Info Cards */}
                    <View style={styles.infoSection}>
                        <View style={styles.infoCard}>
                            <View style={styles.infoIconWrap}>
                                <Icon name="clipboard" size={16} color="#F59E0B" />
                            </View>
                            <Text style={styles.infoText}>
                                Asegúrate de copiar la dirección de depósito desde Guardarian antes de continuar.
                            </Text>
                        </View>
                    </View>

                    {/* Action Buttons */}
                    <View style={styles.actionsContainer}>
                        {/* Convert Button - Primary Blue */}
                        <TouchableOpacity
                            style={styles.convertButton}
                            onPress={onConvert}
                            activeOpacity={0.85}
                        >
                            <View style={styles.buttonContent}>
                                <Icon name="refresh-cw" size={18} color="#fff" />
                                <View style={styles.buttonTextWrap}>
                                    <Text style={styles.convertButtonTitle}>Convertir primero</Text>
                                    <Text style={styles.convertButtonSubtitle}>cUSD → USDC</Text>
                                </View>
                            </View>
                            <Icon name="chevron-right" size={20} color="rgba(255,255,255,0.7)" />
                        </TouchableOpacity>

                        {/* Retirar Button - Amber Secondary */}
                        <TouchableOpacity
                            style={styles.retirarButton}
                            onPress={onRetirar}
                            activeOpacity={0.85}
                        >
                            <View style={styles.buttonContent}>
                                <FAIcon name="bank" size={16} color="#92400E" />
                                <View style={styles.buttonTextWrap}>
                                    <Text style={styles.retirarButtonTitle}>Ya tengo USDC</Text>
                                    <Text style={styles.retirarButtonSubtitle}>Ir a enviar a Guardarian</Text>
                                </View>
                            </View>
                            <Icon name="chevron-right" size={20} color="#D97706" />
                        </TouchableOpacity>

                        {/* Cancel Button - Tertiary */}
                        <TouchableOpacity
                            style={styles.cancelButton}
                            onPress={onCancel}
                            activeOpacity={0.7}
                        >
                            <Text style={styles.cancelButtonText}>Lo haré más tarde</Text>
                        </TouchableOpacity>
                    </View>
                </View>
            </View>
        </Modal>
    );
};

const styles = StyleSheet.create({
    overlay: {
        flex: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.6)',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    modalContainer: {
        backgroundColor: '#fff',
        borderRadius: 24,
        width: width - 40,
        maxWidth: 380,
        padding: 24,
        ...Platform.select({
            ios: {
                shadowColor: '#000',
                shadowOffset: { width: 0, height: 8 },
                shadowOpacity: 0.2,
                shadowRadius: 24,
            },
            android: {
                elevation: 12,
            },
        }),
    },
    header: {
        alignItems: 'center',
        marginBottom: 20,
    },
    iconContainer: {
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: '#ECFDF5',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 16,
        borderWidth: 4,
        borderColor: '#D1FAE5',
    },
    title: {
        fontSize: 22,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 8,
        textAlign: 'center',
    },
    subtitle: {
        fontSize: 15,
        color: '#6B7280',
        textAlign: 'center',
        lineHeight: 22,
    },
    infoSection: {
        marginBottom: 20,
    },
    infoCard: {
        flexDirection: 'row',
        backgroundColor: '#EFF6FF',
        borderRadius: 12,
        padding: 12,
        alignItems: 'flex-start',
        borderWidth: 1,
        borderColor: '#DBEAFE',
    },
    infoIconWrap: {
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: '#fff',
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 10,
    },
    infoText: {
        flex: 1,
        fontSize: 13,
        color: '#1E40AF',
        lineHeight: 18,
    },
    actionsContainer: {
        gap: 12,
    },
    convertButton: {
        backgroundColor: '#3B82F6',
        paddingVertical: 14,
        paddingHorizontal: 16,
        borderRadius: 16,
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        ...Platform.select({
            ios: {
                shadowColor: '#3B82F6',
                shadowOffset: { width: 0, height: 4 },
                shadowOpacity: 0.3,
                shadowRadius: 8,
            },
            android: {
                elevation: 4,
            },
        }),
    },
    buttonContent: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    buttonTextWrap: {
        flexDirection: 'column',
    },
    convertButtonTitle: {
        color: '#fff',
        fontSize: 16,
        fontWeight: '600',
    },
    convertButtonSubtitle: {
        color: 'rgba(255, 255, 255, 0.8)',
        fontSize: 12,
        marginTop: 2,
    },
    retirarButton: {
        backgroundColor: '#FEF3C7',
        paddingVertical: 14,
        paddingHorizontal: 16,
        borderRadius: 16,
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderWidth: 1.5,
        borderColor: '#FCD34D',
    },
    retirarButtonTitle: {
        color: '#92400E',
        fontSize: 16,
        fontWeight: '600',
    },
    retirarButtonSubtitle: {
        color: '#B45309',
        fontSize: 12,
        marginTop: 2,
    },
    cancelButton: {
        paddingVertical: 14,
        alignItems: 'center',
    },
    cancelButtonText: {
        color: '#9CA3AF',
        fontSize: 15,
        fontWeight: '500',
    },
});

export default GuardarianReturnModal;
