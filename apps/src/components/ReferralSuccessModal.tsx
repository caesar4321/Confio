import React, { useEffect } from 'react';
import { View, Text, Modal, StyleSheet, TouchableOpacity, TouchableWithoutFeedback } from 'react-native';

interface ReferralSuccessModalProps {
    visible: boolean;
    onClose: () => void;
    message?: string;
    autoClose?: boolean;
}

const DEFAULT_MESSAGE = "Tienes US$5 en $CONFIO bloqueados. Completa tu primera operación para desbloquearlos.";

export const ReferralSuccessModal: React.FC<ReferralSuccessModalProps> = ({
    visible,
    onClose,
    message = DEFAULT_MESSAGE,
    autoClose = true,
}) => {
    useEffect(() => {
        if (visible && autoClose) {
            const timer = setTimeout(() => {
                onClose();
            }, 3000); // 3 seconds to read
            return () => clearTimeout(timer);
        }
    }, [visible, autoClose, onClose]);

    if (!visible) return null;

    return (
        <Modal visible={visible} transparent animationType="none" onRequestClose={onClose}>
            <TouchableOpacity
                style={styles.modalOverlay}
                activeOpacity={1}
                onPress={onClose}
            >
                <TouchableWithoutFeedback>
                    <View style={styles.successCard}>
                        <Text style={styles.successEmoji}>🎉</Text>
                        <Text style={styles.successTitle}>¡Referidor Registrado!</Text>
                        <Text style={styles.successMessage}>
                            {message}
                        </Text>

                        <TouchableOpacity style={styles.closeButton} onPress={onClose}>
                            <Text style={styles.closeButtonText}>Entendido</Text>
                        </TouchableOpacity>
                    </View>
                </TouchableWithoutFeedback>
            </TouchableOpacity>
        </Modal>
    );
};

const styles = StyleSheet.create({
    modalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    successCard: {
        backgroundColor: 'white',
        borderRadius: 16,
        padding: 32,
        alignItems: 'center',
        margin: 20,
        width: '100%',
        maxWidth: 340,
        shadowColor: "#000",
        shadowOffset: {
            width: 0,
            height: 2,
        },
        shadowOpacity: 0.25,
        shadowRadius: 3.84,
        elevation: 5,
    },
    successEmoji: {
        fontSize: 60,
        marginBottom: 16,
    },
    successTitle: {
        fontSize: 24,
        fontWeight: '700',
        color: '#10B981',
        marginBottom: 8,
        textAlign: 'center',
    },
    successMessage: {
        fontSize: 16,
        color: '#6B7280',
        textAlign: 'center',
        lineHeight: 22,
        marginBottom: 24,
    },
    closeButton: {
        backgroundColor: '#10B981',
        paddingVertical: 12,
        paddingHorizontal: 32,
        borderRadius: 24,
        width: '100%',
        maxWidth: 200,
        alignItems: 'center',
    },
    closeButtonText: {
        color: 'white',
        fontSize: 16,
        fontWeight: '600',
    },
});
