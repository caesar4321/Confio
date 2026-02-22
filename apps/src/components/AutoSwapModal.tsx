import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    ActivityIndicator,
    Platform,
} from 'react-native';

interface AutoSwapModalProps {
    visible: boolean;
    assetType: 'ALGO' | 'USDC' | null;
}

const AutoSwapModal: React.FC<AutoSwapModalProps> = ({ visible, assetType }) => {
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
                        {/* 
                          We use a standard ActivityIndicator as fallback if Lottie is not available, 
                          but typically in this project we have Lottie for loading states.
                          For simplicity here we just use ActivityIndicator to ensure it always renders.
                        */}
                        <ActivityIndicator size="large" color="#34D399" />
                    </View>

                    <Text style={styles.title}>
                        Optimizando tu billetera
                    </Text>

                    <Text style={styles.subtitle}>
                        {assetType === 'ALGO'
                            ? 'Convirtiendo tu depósito de ALGO a cUSD para proteger su valor...'
                            : 'Convirtiendo tu depósito de USDC a cUSD sin comisiones...'}
                    </Text>

                    <Text style={styles.note}>
                        Este proceso es automático y tomará unos segundos.
                    </Text>
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
    }
});

export default AutoSwapModal;
