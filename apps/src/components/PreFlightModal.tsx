import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    TouchableOpacity,
    Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

interface PreFlightModalProps {
    visible: boolean;
    type: 'buy' | 'sell';
    onContinue: () => void;
    onCancel: () => void;
}

const PreFlightModal: React.FC<PreFlightModalProps> = ({
    visible,
    type,
    onContinue,
    onCancel,
}) => {
    const isBuy = type === 'buy';

    const title = isBuy ? 'Solo toma 2 minutos' : 'Para vender tus USDC';
    const subtitle = isBuy
        ? 'Ten esto a mano antes de continuar:'
        : 'Ten esto en cuenta antes de seguir:';

    const checklistItems = isBuy
        ? [
            {
                emoji: '🆔',
                title: 'Documento de Identidad',
                description: 'Ten tu DNI/Cédula a la mano.',
            },
            {
                emoji: '📸',
                title: 'Selfie',
                description: 'Verificaremos que eres tú.',
            },
            {
                emoji: '💳',
                title: 'Tarjeta',
                description: 'Habilitada para compras internacionales.',
            },
        ]
        : [
            {
                emoji: '🏦',
                title: 'Datos Bancarios',
                description: 'Ten a mano el CBU/IBAN de tu banco.',
            },
            {
                emoji: '⚡',
                title: 'Envío Manual',
                description: 'Guardarian te dará una dirección de pago.',
            },
            {
                emoji: '📱',
                title: 'Regresa aquí',
                description: 'Vuelve a Confío para enviar los USDC.',
            },
        ];

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
                    {/* Header */}
                    <View style={styles.header}>
                        <View style={styles.iconContainer}>
                            <Icon name="clock" size={24} color="#72D9BC" />
                        </View>
                        <Text style={styles.title}>{title}</Text>
                        <Text style={styles.subtitle}>{subtitle}</Text>
                    </View>

                    {/* Checklist Items */}
                    <View style={styles.checklistContainer}>
                        {checklistItems.map((item, index) => (
                            <View key={index} style={styles.checklistItem}>
                                <View style={styles.itemIconContainer}>
                                    <Text style={styles.emoji}>{item.emoji}</Text>
                                </View>
                                <View style={styles.itemTextContainer}>
                                    <Text style={styles.itemTitle}>{item.title}</Text>
                                    <Text style={styles.itemDescription}>{item.description}</Text>
                                </View>
                            </View>
                        ))}
                    </View>

                    {/* Actions */}
                    <View style={styles.actionsContainer}>
                        <TouchableOpacity style={styles.primaryButton} onPress={onContinue}>
                            <Text style={styles.primaryButtonText}>Estoy listo</Text>
                            <Icon name="arrow-right" size={20} color="#fff" />
                        </TouchableOpacity>

                        <TouchableOpacity style={styles.secondaryButton} onPress={onCancel}>
                            <Text style={styles.secondaryButtonText}>Más tarde</Text>
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
        width: '100%',
        maxWidth: 340,
        padding: 24,
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
    header: {
        alignItems: 'center',
        marginBottom: 24,
    },
    iconContainer: {
        width: 56,
        height: 56,
        borderRadius: 28,
        backgroundColor: '#ECFDF5',
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
    subtitle: {
        fontSize: 15,
        color: '#6B7280',
        textAlign: 'center',
    },
    checklistContainer: {
        marginBottom: 24,
    },
    checklistItem: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 16,
        backgroundColor: '#F9FAFB',
        padding: 12,
        borderRadius: 16,
    },
    itemIconContainer: {
        width: 40,
        height: 40,
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 12,
        backgroundColor: '#fff',
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    emoji: {
        fontSize: 20,
    },
    itemTextContainer: {
        flex: 1,
    },
    itemTitle: {
        fontSize: 15,
        fontWeight: '600',
        color: '#374151',
        marginBottom: 2,
    },
    itemDescription: {
        fontSize: 13,
        color: '#6B7280',
        lineHeight: 18,
    },
    actionsContainer: {
        gap: 12,
    },
    primaryButton: {
        backgroundColor: '#72D9BC',
        paddingVertical: 14,
        borderRadius: 16,
        flexDirection: 'row',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 8,
        ...Platform.select({
            ios: {
                shadowColor: '#72D9BC',
                shadowOffset: { width: 0, height: 4 },
                shadowOpacity: 0.2,
                shadowRadius: 8,
            },
            android: {
                elevation: 4,
            },
        }),
    },
    primaryButtonText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: '600',
    },
    secondaryButton: {
        paddingVertical: 12,
        alignItems: 'center',
    },
    secondaryButtonText: {
        color: '#6B7280',
        fontSize: 15,
        fontWeight: '500',
    },
});

export default PreFlightModal;
