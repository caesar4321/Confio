import React from 'react';
import {
    Modal,
    View,
    Text,
    TouchableOpacity,
    StyleSheet,
    ScrollView,
} from 'react-native';

interface BackupEntry {
    id: string | null | undefined;
    createdAt: string;
    lastBackupAt: string;
    deviceHint: string;
    providerHint: string;
}

interface ExistingBackupModalProps {
    visible: boolean;
    entries: BackupEntry[];
    hasLegacy?: boolean;
    onRestore: (entry: BackupEntry | null) => void;
    onUseCurrentWallet: () => void;
    onCancel: () => void;
}

/**
 * Unified modal for backup detection.
 * Shows all backup entries and lets user choose which one to restore.
 */
export const ExistingBackupModal: React.FC<ExistingBackupModalProps> = ({
    visible,
    entries,
    hasLegacy,
    onRestore,
    onUseCurrentWallet,
    onCancel,
}) => {
    const formatDate = (isoString: string) => {
        try {
            const date = new Date(isoString);
            return date.toLocaleDateString('es-ES', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
            });
        } catch {
            return isoString;
        }
    };

    // Get platform from deviceHint
    const getPlatform = (deviceHint: string): string => {
        const hint = deviceHint?.toLowerCase() || '';
        if (hint.includes('android')) return 'Android';
        if (hint.includes('ios') || hint.includes('iphone') || hint.includes('ipad')) return 'iOS';
        return '';
    };

    return (
        <Modal
            visible={visible}
            transparent
            animationType="fade"
            onRequestClose={() => { }}
        >
            <View style={styles.overlay}>
                <View style={styles.container}>
                    <View style={styles.iconContainer}>
                        <Text style={styles.icon}>📱</Text>
                    </View>

                    <Text style={styles.title}>Respaldos Encontrados</Text>

                    <Text style={styles.description}>
                        Selecciona una billetera para restaurar:
                    </Text>

                    {hasLegacy && entries.length === 0 ? (
                        <TouchableOpacity
                            style={styles.entryButton}
                            onPress={() => onRestore(null)}
                        >
                            <View style={styles.entryContent}>
                                <Text style={styles.entryDevice}>📂 Respaldo anterior</Text>
                                <Text style={styles.entryDate}>Billetera legacy</Text>
                            </View>
                            <Text style={styles.entryArrow}>→</Text>
                        </TouchableOpacity>
                    ) : (
                        <ScrollView style={styles.entriesList} showsVerticalScrollIndicator={false}>
                            {entries.map((entry, index) => {
                                const platform = getPlatform(entry.deviceHint);
                                return (
                                    <TouchableOpacity
                                        key={entry.id || `entry-${index}`}
                                        style={styles.entryButton}
                                        onPress={() => onRestore(entry)}
                                    >
                                        <View style={styles.entryContent}>
                                            <Text style={styles.entryDevice}>
                                                {platform === 'iOS' ? '🍎' : platform === 'Android' ? '🤖' : '📱'} {entry.deviceHint}
                                            </Text>
                                            <Text style={styles.entryDate}>
                                                Último respaldo: {formatDate(entry.lastBackupAt)}
                                            </Text>
                                        </View>
                                        <Text style={styles.entryArrow}>→</Text>
                                    </TouchableOpacity>
                                );
                            })}
                        </ScrollView>
                    )}
                    <TouchableOpacity
                        style={[styles.button, styles.secondaryButton]}
                        onPress={onUseCurrentWallet}
                    >
                        <Text style={styles.secondaryButtonText}>
                            Usar billetera actual
                        </Text>
                    </TouchableOpacity>

                    <Text style={styles.warning}>
                        ⚠️ Restaurar otra billetera reemplazará tu billetera actual.
                    </Text>
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
    container: {
        backgroundColor: '#fff',
        borderRadius: 20,
        padding: 24,
        width: '100%',
        maxWidth: 360,
        maxHeight: '80%',
        alignItems: 'center',
    },
    iconContainer: {
        marginBottom: 16,
    },
    icon: {
        fontSize: 48,
    },
    title: {
        fontSize: 20,
        fontWeight: '700',
        color: '#1f2937',
        marginBottom: 12,
        textAlign: 'center',
    },
    description: {
        fontSize: 15,
        color: '#4b5563',
        textAlign: 'center',
        marginBottom: 16,
        lineHeight: 22,
    },
    entriesList: {
        width: '100%',
        maxHeight: 200,
    },
    entryButton: {
        backgroundColor: '#f3f4f6',
        borderRadius: 12,
        padding: 14,
        marginBottom: 10,
        width: '100%',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    entryContent: {
        flex: 1,
    },
    entryDevice: {
        fontSize: 15,
        fontWeight: '600',
        color: '#1f2937',
    },
    entryDate: {
        fontSize: 13,
        color: '#6b7280',
        marginTop: 4,
    },
    entryArrow: {
        fontSize: 18,
        color: '#10b981',
        fontWeight: '600',
        marginLeft: 10,
    },
    buttonContainer: {
        width: '100%',
        gap: 10,
        marginTop: 16,
    },
    button: {
        paddingVertical: 14,
        paddingHorizontal: 24,
        borderRadius: 12,
        alignItems: 'center',
    },
    secondaryButton: {
        backgroundColor: '#e5e7eb',
    },
    secondaryButtonText: {
        color: '#4b5563',
        fontSize: 16,
        fontWeight: '600',
    },
    cancelButton: {
        paddingVertical: 10,
        alignItems: 'center',
    },
    cancelButtonText: {
        color: '#9ca3af',
        fontSize: 14,
    },
    warning: {
        fontSize: 12,
        color: '#f59e0b',
        textAlign: 'center',
        marginTop: 16,
        lineHeight: 16,
    },
});

export default ExistingBackupModal;
