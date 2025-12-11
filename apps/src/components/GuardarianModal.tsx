import React, { useState } from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    TouchableOpacity,
    Dimensions,
    Clipboard,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

interface GuardarianModalProps {
    visible: boolean;
    type: 'buy' | 'sell';
    address?: string;
    onClose: () => void;
    onContinue: () => void;
}

const { width } = Dimensions.get('window');

export const GuardarianModal: React.FC<GuardarianModalProps> = ({
    visible,
    type,
    address,
    onClose,
    onContinue,
}) => {
    const [copied, setCopied] = useState(false);
    const [hasCopiedOnce, setHasCopiedOnce] = useState(false);

    const handleCopy = () => {
        if (address) {
            Clipboard.setString(address);
            setCopied(true);
            setHasCopiedOnce(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    const isContinueDisabled = type === 'buy' && !hasCopiedOnce;

    return (
        <Modal
            visible={visible}
            transparent={true}
            animationType="fade"
            statusBarTranslucent={true}
            onRequestClose={onClose}
        >
            <View style={styles.overlay}>
                <View style={styles.modalContainer}>
                    <TouchableOpacity style={styles.closeButton} onPress={onClose}>
                        <Icon name="x" size={24} color="#6B7280" />
                    </TouchableOpacity>

                    <View style={styles.iconContainer}>
                        <Icon
                            name={type === 'buy' ? 'copy' : 'info'}
                            size={32}
                            color="#72D9BC"
                        />
                    </View>

                    <Text style={styles.title}>
                        {type === 'buy' ? 'Copia tu dirección' : 'Paso importante'}
                    </Text>

                    <Text style={styles.description}>
                        {type === 'buy'
                            ? 'Cuando Guardarian te pida la dirección de billetera, pega la dirección que verás a continuación.'
                            : 'Al finalizar la venta en Guardarian, deberás enviar tus USDC manualmente desde el menú "Retirar" en Confío.'}
                    </Text>

                    {type === 'buy' && address && (
                        <TouchableOpacity style={styles.copyContainer} onPress={handleCopy}>
                            <View style={styles.addressBox}>
                                <Text style={styles.addressText} numberOfLines={1} ellipsizeMode="middle">
                                    {address}
                                </Text>
                            </View>
                            <View style={[styles.copyButton, copied && styles.copyButtonActive]}>
                                <Icon name={copied ? 'check' : 'copy'} size={16} color="#fff" />
                                <Text style={styles.copyButtonText}>
                                    {copied ? '¡Copiado!' : 'Copiar'}
                                </Text>
                            </View>
                        </TouchableOpacity>
                    )}

                    <TouchableOpacity
                        style={[styles.ctaButton, isContinueDisabled && styles.ctaButtonDisabled]}
                        onPress={onContinue}
                        disabled={isContinueDisabled}
                    >
                        <Text style={[styles.ctaButtonText, isContinueDisabled && styles.ctaButtonTextDisabled]}>
                            {isContinueDisabled ? 'Copia la dirección para continuar' : 'Entendido, continuar'}
                        </Text>
                        <Icon
                            name="arrow-right"
                            size={20}
                            color={isContinueDisabled ? '#9CA3AF' : '#fff'}
                        />
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
        width: width - 40,
        backgroundColor: '#fff',
        borderRadius: 24,
        padding: 24,
        alignItems: 'center',
        shadowColor: '#000',
        shadowOpacity: 0.1,
        shadowRadius: 20,
        shadowOffset: { width: 0, height: 10 },
        elevation: 5,
    },
    closeButton: {
        position: 'absolute',
        top: 16,
        right: 16,
        padding: 8,
        zIndex: 1,
    },
    iconContainer: {
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: '#ECFDF5',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 16,
    },
    title: {
        fontSize: 20,
        fontWeight: '700',
        color: '#111827',
        marginBottom: 8,
        textAlign: 'center',
    },
    description: {
        fontSize: 15,
        color: '#6B7280',
        textAlign: 'center',
        lineHeight: 22,
        marginBottom: 24,
    },
    copyContainer: {
        width: '100%',
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#F3F4F6',
        borderRadius: 12,
        padding: 4,
        marginBottom: 24,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    addressBox: {
        flex: 1,
        paddingHorizontal: 12,
    },
    addressText: {
        fontSize: 13,
        color: '#374151',
        fontFamily: 'monospace',
    },
    copyButton: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#6B7280',
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: 8,
        gap: 6,
    },
    copyButtonActive: {
        backgroundColor: '#10B981',
    },
    copyButtonText: {
        fontSize: 12,
        fontWeight: '600',
        color: '#fff',
    },
    ctaButton: {
        width: '100%',
        backgroundColor: '#72D9BC',
        borderRadius: 16,
        paddingVertical: 16,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        shadowColor: '#72D9BC',
        shadowOpacity: 0.3,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 4,
    },
    ctaButtonDisabled: {
        backgroundColor: '#E5E7EB',
        shadowOpacity: 0,
    },
    ctaButtonText: {
        fontSize: 16,
        fontWeight: '700',
        color: '#fff',
    },
    ctaButtonTextDisabled: {
        color: '#9CA3AF',
    },
});
