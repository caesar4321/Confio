import React from 'react';
import { View, Text, Modal, StyleSheet, TouchableOpacity, TouchableWithoutFeedback, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

interface TelegramGroupModalProps {
    visible: boolean;
    onClose: () => void;
    telegramUrl: string;
}

export const TelegramGroupModal: React.FC<TelegramGroupModalProps> = ({
    visible,
    onClose,
    telegramUrl,
}) => {
    const handleJoin = async () => {
        try {
            await Linking.openURL(telegramUrl);
        } catch { }
        onClose();
    };

    if (!visible) return null;

    return (
        <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
            <TouchableOpacity
                style={styles.modalOverlay}
                activeOpacity={1}
                onPress={onClose}
            >
                <TouchableWithoutFeedback>
                    <View style={styles.card}>
                        <View style={styles.iconContainer}>
                            <Icon name="send" size={36} color="#fff" />
                        </View>

                        <Text style={styles.title}>¡Únete a nuestro grupo privado!</Text>

                        <Text style={styles.message}>
                            Tenemos un grupo exclusivo de Telegram para participantes de la preventa de $CONFIO. Conéctate con la comunidad fundadora.
                        </Text>

                        <TouchableOpacity style={styles.joinButton} onPress={handleJoin}>
                            <Icon name="send" size={18} color="#fff" />
                            <Text style={styles.joinButtonText}>Unirme al grupo</Text>
                        </TouchableOpacity>

                        <TouchableOpacity style={styles.dismissButton} onPress={onClose}>
                            <Text style={styles.dismissButtonText}>Ahora no</Text>
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
    card: {
        backgroundColor: 'white',
        borderRadius: 16,
        padding: 32,
        alignItems: 'center',
        margin: 20,
        width: '100%',
        maxWidth: 340,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.25,
        shadowRadius: 3.84,
        elevation: 5,
    },
    iconContainer: {
        width: 72,
        height: 72,
        borderRadius: 36,
        backgroundColor: '#0088cc',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 16,
    },
    title: {
        fontSize: 22,
        fontWeight: '700',
        color: colors.dark,
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
    joinButton: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        backgroundColor: '#0088cc',
        paddingVertical: 14,
        paddingHorizontal: 32,
        borderRadius: 24,
        width: '100%',
        justifyContent: 'center',
        marginBottom: 12,
    },
    joinButtonText: {
        color: 'white',
        fontSize: 16,
        fontWeight: '600',
    },
    dismissButton: {
        paddingVertical: 8,
        paddingHorizontal: 16,
    },
    dismissButtonText: {
        color: '#9CA3AF',
        fontSize: 14,
        fontWeight: '500',
    },
});
