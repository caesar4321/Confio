import React, { useState, useCallback } from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    TouchableOpacity,
    ScrollView,
    TextInput,
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useMutation } from '@apollo/client';
import { SUBMIT_CONFIO_ICP, GET_ME } from '../apollo/queries';

type IcpTag =
    | 'proteger_ahorros'
    | 'generar_rendimiento'
    | 'comprar_confio'
    | 'enviar_recibir_pagos'
    | 'importacion_exportacion'
    | 'otra';

const ICP_OPTIONS: { tag: IcpTag; label: string; icon: string }[] = [
    { tag: 'proteger_ahorros', label: 'Proteger mis ahorros en dólares', icon: 'shield-check' },
    { tag: 'generar_rendimiento', label: 'Generar rendimiento sobre mis dólares', icon: 'trending-up' },
    { tag: 'comprar_confio', label: 'Comprar CONFIO (token)', icon: 'star-four-points' },
    { tag: 'enviar_recibir_pagos', label: 'Enviar o recibir pagos', icon: 'send' },
    { tag: 'importacion_exportacion', label: 'Importación / exportación o negocio', icon: 'briefcase-outline' },
    { tag: 'otra', label: 'Otra razón', icon: 'message-text-outline' },
];

interface ConfioIcpModalProps {
    visible: boolean;
    onClose: () => void;
}

export const ConfioIcpModal: React.FC<ConfioIcpModalProps> = ({ visible, onClose }) => {
    const insets = useSafeAreaInsets();
    const { height } = useWindowDimensions();
    const modalMaxHeight = Math.max(420, height - insets.top - insets.bottom - 32);

    const [selected, setSelected] = useState<Set<IcpTag>>(new Set());
    const [otherText, setOtherText] = useState('');
    const [submitIcp, { loading }] = useMutation(SUBMIT_CONFIO_ICP, {
        refetchQueries: [{ query: GET_ME }],
        awaitRefetchQueries: true,
    });

    const toggle = useCallback((tag: IcpTag) => {
        setSelected(prev => {
            const next = new Set(prev);
            if (next.has(tag)) {
                next.delete(tag);
            } else {
                next.add(tag);
            }
            return next;
        });
    }, []);

    const submit = useCallback(async (tags: IcpTag[]) => {
        try {
            await submitIcp({
                variables: {
                    tags,
                    otherText: tags.includes('otra') ? otherText.trim().slice(0, 500) : null,
                },
            });
        } catch {
            // Swallow — GET_ME refetch will retry resolution on next interaction;
            // mutation is idempotent (re-submission returns success no-op).
        } finally {
            onClose();
        }
    }, [submitIcp, otherText, onClose]);

    const handleContinue = () => submit(Array.from(selected));
    const handleSkip = () => submit([]);

    const showOtherInput = selected.has('otra');

    return (
        <Modal animationType="fade" transparent visible={visible} statusBarTranslucent onRequestClose={() => { }}>
            <KeyboardAvoidingView
                style={styles.flex1}
                behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            >
            <View
                style={[
                    styles.centered,
                    { paddingTop: Math.max(insets.top, 16), paddingBottom: Math.max(insets.bottom, 16) },
                ]}
            >
                <View style={[styles.card, { maxHeight: modalMaxHeight }]}>
                    <ScrollView
                        style={styles.scroll}
                        contentContainerStyle={styles.scrollContent}
                        bounces={false}
                        keyboardShouldPersistTaps="handled"
                    >
                        <View style={styles.iconWrap}>
                            <Icon name="party-popper" size={48} color="#10B981" />
                        </View>
                        <Text style={styles.title}>¡Ya tienes tus primeros dólares en Confío!</Text>
                        <Text style={styles.subtitle}>Una pregunta rápida para entender mejor cómo ayudarte.</Text>
                        <Text style={styles.question}>¿Cuáles son tus principales razones para usar Confío?</Text>
                        <Text style={styles.hint}>Puedes seleccionar varias</Text>

                        <View style={styles.options}>
                            {ICP_OPTIONS.map(opt => {
                                const isSelected = selected.has(opt.tag);
                                return (
                                    <TouchableOpacity
                                        key={opt.tag}
                                        style={[styles.option, isSelected && styles.optionSelected]}
                                        onPress={() => toggle(opt.tag)}
                                        activeOpacity={0.8}
                                    >
                                        <Icon
                                            name={isSelected ? 'checkbox-marked' : 'checkbox-blank-outline'}
                                            size={22}
                                            color={isSelected ? '#10B981' : '#9CA3AF'}
                                        />
                                        <Icon name={opt.icon} size={20} color="#4B5563" style={styles.optionIcon} />
                                        <Text style={[styles.optionLabel, isSelected && styles.optionLabelSelected]}>
                                            {opt.label}
                                        </Text>
                                    </TouchableOpacity>
                                );
                            })}
                        </View>

                        {showOtherInput && (
                            <TextInput
                                style={styles.otherInput}
                                placeholder="Cuéntanos en una línea…"
                                placeholderTextColor="#9CA3AF"
                                value={otherText}
                                onChangeText={setOtherText}
                                multiline
                                maxLength={500}
                            />
                        )}
                    </ScrollView>

                    <View style={styles.footer}>
                        <TouchableOpacity
                            style={[styles.btn, styles.btnSkip]}
                            onPress={handleSkip}
                            disabled={loading}
                        >
                            <Text style={styles.btnSkipText}>Saltar</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={[styles.btn, styles.btnPrimary, selected.size === 0 && styles.btnDisabled]}
                            onPress={handleContinue}
                            disabled={loading || selected.size === 0}
                        >
                            {loading ? (
                                <ActivityIndicator color="#fff" />
                            ) : (
                                <Text style={styles.btnPrimaryText}>Continuar</Text>
                            )}
                        </TouchableOpacity>
                    </View>
                </View>
            </View>
            </KeyboardAvoidingView>
        </Modal>
    );
};

const styles = StyleSheet.create({
    flex1: { flex: 1 },
    centered: {
        flex: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 16,
    },
    card: {
        width: '100%',
        maxWidth: 480,
        backgroundColor: '#fff',
        borderRadius: 16,
        overflow: 'hidden',
    },
    scroll: { flexGrow: 0 },
    scrollContent: { padding: 24 },
    iconWrap: {
        alignSelf: 'center',
        backgroundColor: '#ECFDF5',
        width: 80,
        height: 80,
        borderRadius: 40,
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 16,
    },
    title: {
        fontSize: 20,
        fontWeight: '700',
        color: '#111827',
        textAlign: 'center',
        marginBottom: 8,
    },
    subtitle: {
        fontSize: 14,
        color: '#4B5563',
        textAlign: 'center',
        marginBottom: 16,
        lineHeight: 20,
    },
    question: {
        fontSize: 15,
        fontWeight: '600',
        color: '#111827',
        marginTop: 4,
    },
    hint: {
        fontSize: 12,
        color: '#6B7280',
        marginTop: 4,
        marginBottom: 12,
    },
    options: { gap: 8 },
    option: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 12,
        paddingHorizontal: 12,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: '#E5E7EB',
        backgroundColor: '#fff',
    },
    optionSelected: {
        borderColor: '#10B981',
        backgroundColor: '#F0FDF4',
    },
    optionIcon: { marginHorizontal: 10 },
    optionLabel: {
        flex: 1,
        fontSize: 14,
        color: '#374151',
    },
    optionLabelSelected: { color: '#065F46', fontWeight: '600' },
    otherInput: {
        marginTop: 12,
        borderWidth: 1,
        borderColor: '#E5E7EB',
        borderRadius: 10,
        padding: 12,
        fontSize: 14,
        color: '#111827',
        minHeight: 64,
        textAlignVertical: 'top',
    },
    footer: {
        flexDirection: 'row',
        gap: 12,
        padding: 16,
        borderTopWidth: 1,
        borderTopColor: '#F3F4F6',
    },
    btn: {
        flex: 1,
        height: 48,
        borderRadius: 10,
        justifyContent: 'center',
        alignItems: 'center',
    },
    btnSkip: { backgroundColor: '#F3F4F6' },
    btnSkipText: { color: '#374151', fontSize: 15, fontWeight: '600' },
    btnPrimary: { backgroundColor: '#10B981' },
    btnPrimaryText: { color: '#fff', fontSize: 15, fontWeight: '700' },
    btnDisabled: { backgroundColor: '#A7F3D0' },
});
