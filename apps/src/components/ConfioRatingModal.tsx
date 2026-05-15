import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
    View,
    Text,
    StyleSheet,
    Modal,
    TouchableOpacity,
    TextInput,
    ActivityIndicator,
    Linking,
    Platform,
    Keyboard,
    useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useMutation } from '@apollo/client';
import { SUBMIT_CONFIO_RATING, GET_ME } from '../apollo/queries';

const IOS_APP_STORE_ID = '6472662314';
const ANDROID_PACKAGE = 'com.Confio.Confio';
const PLAY_STORE_PACKAGE = 'com.android.vending';

const iosReviewUrl = `itms-apps://itunes.apple.com/app/id${IOS_APP_STORE_ID}?action=write-review`;
// Force the resolver to Google Play specifically (not Xiaomi Mi Store, Huawei
// AppGallery, etc., which all advertise the `market://` intent on devices
// where they're installed alongside Play).
const androidReviewUrl = `intent://details?id=${ANDROID_PACKAGE}#Intent;scheme=market;package=${PLAY_STORE_PACKAGE};end`;

type Step = 'stars' | 'action' | 'feedback';
type RatingAction = 'FEEDBACK' | 'STORE' | 'SKIP';

interface ConfioRatingModalProps {
    visible: boolean;
    onClose: () => void;
}

export const ConfioRatingModal: React.FC<ConfioRatingModalProps> = ({ visible, onClose }) => {
    const insets = useSafeAreaInsets();
    const { height } = useWindowDimensions();
    const modalMaxHeight = Math.max(360, height - insets.top - insets.bottom - 32);

    const [step, setStep] = useState<Step>('stars');
    const [stars, setStars] = useState(0);
    const [feedbackText, setFeedbackText] = useState('');
    const feedbackInputRef = useRef<TextInput>(null);
    const [submitRating, { loading }] = useMutation(SUBMIT_CONFIO_RATING, {
        refetchQueries: [{ query: GET_ME }],
        awaitRefetchQueries: true,
    });

    // autoFocus inside a Modal can race with the modal animation; focus
    // imperatively after a short delay so the keyboard reliably appears.
    useEffect(() => {
        if (step !== 'feedback') return;
        const t = setTimeout(() => feedbackInputRef.current?.focus(), 250);
        return () => clearTimeout(t);
    }, [step]);

    const reset = useCallback(() => {
        setStep('stars');
        setStars(0);
        setFeedbackText('');
    }, []);

    const closeAndReset = useCallback(() => {
        reset();
        onClose();
    }, [reset, onClose]);

    const submit = useCallback(
        async (action: RatingAction, text: string | null) => {
            if (stars < 1) return;
            try {
                await submitRating({
                    variables: { stars, action, feedbackText: text },
                });
            } catch {
                // Idempotent on the server (re-submission returns no-op).
            }
        },
        [submitRating, stars],
    );

    const openStore = useCallback(async () => {
        const url = Platform.OS === 'ios' ? iosReviewUrl : androidReviewUrl;
        try {
            await Linking.openURL(url);
        } catch {
            // If the deeplink fails, the store may not be installed on the
            // device (e.g. AOSP build). Fall back to https store page.
            const fallback =
                Platform.OS === 'ios'
                    ? `https://apps.apple.com/app/id${IOS_APP_STORE_ID}`
                    : `https://play.google.com/store/apps/details?id=${ANDROID_PACKAGE}`;
            try {
                await Linking.openURL(fallback);
            } catch {
                // No usable store — still mark the rating captured.
            }
        }
    }, []);

    const handleStoreAction = useCallback(async () => {
        await submit('STORE', null);
        await openStore();
        closeAndReset();
    }, [submit, openStore, closeAndReset]);

    const handleFeedbackSubmit = useCallback(async () => {
        const text = feedbackText.trim().slice(0, 500);
        if (!text) {
            // Empty feedback collapses to SKIP semantically.
            await submit('SKIP', null);
        } else {
            await submit('FEEDBACK', text);
        }
        closeAndReset();
    }, [submit, feedbackText, closeAndReset]);

    const handleSkip = useCallback(async () => {
        await submit('SKIP', null);
        closeAndReset();
    }, [submit, closeAndReset]);

    return (
        <Modal animationType="fade" transparent visible={visible} statusBarTranslucent onRequestClose={() => { }}>
            <View
                style={[
                    styles.centered,
                    { paddingTop: Math.max(insets.top, 16), paddingBottom: Math.max(insets.bottom, 16) },
                ]}
            >
                <View style={[styles.card, { maxHeight: modalMaxHeight }]}>
                    {step === 'stars' && (
                        <View style={styles.body}>
                            <Text style={styles.title}>¿Cómo ha sido tu experiencia con Confío hasta ahora?</Text>
                            <View style={styles.starsRow}>
                                {[1, 2, 3, 4, 5].map(n => (
                                    <TouchableOpacity key={n} onPress={() => setStars(n)} hitSlop={8}>
                                        <Icon
                                            name={n <= stars ? 'star' : 'star-outline'}
                                            size={40}
                                            color={n <= stars ? '#F59E0B' : '#D1D5DB'}
                                        />
                                    </TouchableOpacity>
                                ))}
                            </View>
                            <View style={styles.footer}>
                                <TouchableOpacity
                                    style={[styles.btn, styles.btnSkip]}
                                    onPress={handleSkip}
                                    disabled={loading}
                                >
                                    <Text style={styles.btnSkipText}>Saltar</Text>
                                </TouchableOpacity>
                                <TouchableOpacity
                                    style={[styles.btn, styles.btnPrimary, stars === 0 && styles.btnDisabled]}
                                    onPress={() => setStep('action')}
                                    disabled={stars === 0}
                                >
                                    <Text style={styles.btnPrimaryText}>Continuar</Text>
                                </TouchableOpacity>
                            </View>
                        </View>
                    )}

                    {step === 'action' && (
                        <View style={styles.body}>
                            <Text style={styles.title}>¿Te gustaría compartir tu experiencia?</Text>
                            <View style={styles.actionList}>
                                <TouchableOpacity
                                    style={styles.actionRow}
                                    onPress={() => setStep('feedback')}
                                    disabled={loading}
                                >
                                    <Icon name="message-text-outline" size={22} color="#4F46E5" />
                                    <Text style={styles.actionLabel}>Cuéntanos qué podemos mejorar</Text>
                                </TouchableOpacity>
                                <TouchableOpacity
                                    style={styles.actionRow}
                                    onPress={handleStoreAction}
                                    disabled={loading}
                                >
                                    <Icon name="star-outline" size={22} color="#F59E0B" />
                                    <Text style={styles.actionLabel}>
                                        Calificar en {Platform.OS === 'ios' ? 'App Store' : 'Google Play'}
                                    </Text>
                                </TouchableOpacity>
                                <TouchableOpacity
                                    style={[styles.actionRow, styles.actionSkip]}
                                    onPress={handleSkip}
                                    disabled={loading}
                                >
                                    <Text style={styles.actionSkipText}>Saltar</Text>
                                </TouchableOpacity>
                            </View>
                            {loading && (
                                <ActivityIndicator color="#10B981" style={{ marginTop: 8 }} />
                            )}
                        </View>
                    )}

                    {step === 'feedback' && (
                        <View style={styles.body}>
                            <Text style={styles.title}>¿Qué podemos mejorar?</Text>
                            <TextInput
                                ref={feedbackInputRef}
                                style={styles.feedbackInput}
                                placeholder="Tu comentario nos ayuda a hacer Confío mejor."
                                placeholderTextColor="#9CA3AF"
                                value={feedbackText}
                                onChangeText={setFeedbackText}
                                multiline
                                maxLength={500}
                            />
                            <View style={styles.footer}>
                                <TouchableOpacity
                                    style={[styles.btn, styles.btnSkip]}
                                    onPress={() => { Keyboard.dismiss(); setStep('action'); }}
                                    disabled={loading}
                                >
                                    <Text style={styles.btnSkipText}>Atrás</Text>
                                </TouchableOpacity>
                                <TouchableOpacity
                                    style={[styles.btn, styles.btnPrimary]}
                                    onPress={() => { Keyboard.dismiss(); handleFeedbackSubmit(); }}
                                    disabled={loading}
                                >
                                    {loading ? (
                                        <ActivityIndicator color="#fff" />
                                    ) : (
                                        <Text style={styles.btnPrimaryText}>Enviar</Text>
                                    )}
                                </TouchableOpacity>
                            </View>
                        </View>
                    )}
                </View>
            </View>
        </Modal>
    );
};

const styles = StyleSheet.create({
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
    body: { padding: 24 },
    title: {
        fontSize: 18,
        fontWeight: '700',
        color: '#111827',
        textAlign: 'center',
        marginBottom: 16,
    },
    starsRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginVertical: 16,
        paddingHorizontal: 12,
    },
    actionList: { gap: 10, marginTop: 8 },
    actionRow: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 14,
        paddingHorizontal: 14,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: '#E5E7EB',
        gap: 12,
    },
    actionLabel: { flex: 1, fontSize: 15, color: '#374151', fontWeight: '600' },
    actionSkip: { borderColor: 'transparent', justifyContent: 'center' },
    actionSkipText: { color: '#6B7280', fontSize: 14, textAlign: 'center', flex: 1 },
    feedbackInput: {
        borderWidth: 1,
        borderColor: '#E5E7EB',
        borderRadius: 10,
        padding: 12,
        fontSize: 14,
        color: '#111827',
        minHeight: 120,
        textAlignVertical: 'top',
    },
    footer: {
        flexDirection: 'row',
        gap: 12,
        marginTop: 20,
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
