import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    ActivityIndicator,
    Platform,
    TouchableOpacity,
} from 'react-native';

interface AutoSwapModalProps {
    visible: boolean;
    assetType: 'ALGO' | 'USDC' | null;
    mode?: 'processing' | 'wallet_recovery_required';
    onClose?: () => void;
}

const AutoSwapModal: React.FC<AutoSwapModalProps> = ({
    visible,
    assetType,
    mode = 'processing',
    onClose
}) => {
    const needsRecovery = mode === 'wallet_recovery_required';

    return (
        <Modal
            visible={visible}
            transparent
            animationType="fade"
            statusBarTranslucent
        >
            <View style={styles.overlay}>
                <View style={styles.modalContainer}>
                    <View style={styles.animationContainer}>
                        {needsRecovery ? (
                            <Text style={styles.iconText}>!</Text>
                        ) : (
                            <ActivityIndicator size="large" color="#34D399" />
                        )}
                    </View>

                    <Text style={styles.title}>
                        {needsRecovery ? 'Revisa tu billetera' : 'Optimizando tu billetera'}
                    </Text>

                    <Text style={styles.subtitle}>
                        {needsRecovery
                            ? 'No pudimos firmar la conversión automática. Actualiza la app, vuelve a abrir Confío e inicia sesión otra vez. Si continúa, restaura o activa tu respaldo desde Perfil.'
                            : assetType === 'ALGO'
                                ? 'Convirtiendo tu depósito de ALGO a cUSD para proteger su valor...'
                                : 'Convirtiendo tu depósito de USDC a cUSD sin comisiones...'}
                    </Text>

                    <Text style={styles.note}>
                        {needsRecovery
                            ? 'Tus fondos siguen seguros en tu billetera.'
                            : 'Este proceso es automático y tomará unos segundos.'}
                    </Text>

                    {needsRecovery && onClose ? (
                        <TouchableOpacity style={styles.primaryButton} onPress={onClose}>
                            <Text style={styles.primaryButtonText}>Entendido</Text>
                        </TouchableOpacity>
                    ) : null}
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
        padding: 24,
    },
    modalContainer: {
        backgroundColor: '#fff',
        borderRadius: 24,
        padding: 32,
        width: '100%',
        maxWidth: 340,
        alignItems: 'center',
        ...Platform.select({
            ios: {
                shadowColor: '#000',
                shadowOffset: { width: 0, height: 4 },
                shadowOpacity: 0.15,
                shadowRadius: 12,
            },
            android: {
                elevation: 8,
            },
        }),
    },
    animationContainer: {
        width: 80,
        height: 80,
        borderRadius: 40,
        backgroundColor: '#ECFDF5',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 20,
    },
    title: {
        fontSize: 20,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 12,
        textAlign: 'center',
    },
    subtitle: {
        fontSize: 15,
        color: '#4B5563',
        textAlign: 'center',
        marginBottom: 16,
        lineHeight: 22,
    },
    note: {
        fontSize: 13,
        color: '#9CA3AF',
        textAlign: 'center',
        fontStyle: 'italic',
    },
    iconText: {
        color: '#DC2626',
        fontSize: 34,
        fontWeight: '800',
        lineHeight: 40,
    },
    primaryButton: {
        marginTop: 22,
        backgroundColor: '#34D399',
        borderRadius: 8,
        minHeight: 44,
        paddingHorizontal: 24,
        alignItems: 'center',
        justifyContent: 'center',
        alignSelf: 'stretch',
    },
    primaryButtonText: {
        color: '#FFFFFF',
        fontSize: 15,
        fontWeight: '700',
        textAlign: 'center',
    }
});

export default AutoSwapModal;
