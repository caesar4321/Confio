import React from 'react';
import { StyleSheet, View, Text, TouchableOpacity, Modal, Dimensions } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { BlurView } from '@react-native-community/blur';

interface ConvertModalProps {
    visible: boolean;
    onConvert: () => void;
    onCancel: () => void;
}

const { width } = Dimensions.get('window');

const ConvertModal: React.FC<ConvertModalProps> = ({ visible, onConvert, onCancel }) => {
    return (
        <Modal
            visible={visible}
            transparent
            animationType="fade"
            statusBarTranslucent
        >
            <View style={styles.overlay}>
                <View style={styles.modalContainer}>
                    <View style={styles.iconContainer}>
                        <Icon name="refresh-cw" size={32} color="#3B82F6" />
                    </View>

                    <Text style={styles.title}>¡Llegaron tus USDC!</Text>
                    <Text style={styles.message}>
                        Para usar tu saldo, necesitas convertirlo a cUSD. Es gratis y al instante.
                    </Text>

                    <TouchableOpacity style={styles.primaryButton} onPress={onConvert}>
                        <Text style={styles.primaryButtonText}>Convertir ahora</Text>
                    </TouchableOpacity>

                    <TouchableOpacity style={styles.secondaryButton} onPress={onCancel}>
                        <Text style={styles.secondaryButtonText}>Más tarde</Text>
                    </TouchableOpacity>
                </View>
            </View>
        </Modal>
    );
};

const styles = StyleSheet.create({
    overlay: {
        flex: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    modalContainer: {
        backgroundColor: 'white',
        borderRadius: 24,
        padding: 24,
        width: width - 40,
        alignItems: 'center',
        shadowColor: '#000',
        shadowOffset: {
            width: 0,
            height: 4,
        },
        shadowOpacity: 0.25,
        shadowRadius: 12,
        elevation: 10,
    },
    iconContainer: {
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: '#EFF6FF',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 16,
    },
    title: {
        fontSize: 20,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 8,
        textAlign: 'center',
    },
    message: {
        fontSize: 15,
        color: '#6B7280',
        textAlign: 'center',
        lineHeight: 22,
        marginBottom: 24,
    },
    primaryButton: {
        backgroundColor: '#3B82F6',
        width: '100%',
        paddingVertical: 14,
        borderRadius: 16,
        alignItems: 'center',
        marginBottom: 12,
    },
    primaryButtonText: {
        color: 'white',
        fontSize: 16,
        fontWeight: '600',
    },
    secondaryButton: {
        width: '100%',
        paddingVertical: 14,
        alignItems: 'center',
    },
    secondaryButtonText: {
        color: '#6B7280',
        fontSize: 16,
        fontWeight: '600',
    },
});

export default ConvertModal;
