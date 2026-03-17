import React from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

type Props = {
  primaryLabel: string;
  onPrimaryPress: () => void;
  primaryDisabled?: boolean;
  primaryLoading?: boolean;
  primaryIconName?: string;
  secondaryLabel?: string;
  onSecondaryPress?: () => void;
};

export const RampActionBar = ({
  primaryLabel,
  onPrimaryPress,
  primaryDisabled = false,
  primaryLoading = false,
  primaryIconName,
  secondaryLabel,
  onSecondaryPress,
}: Props) => {
  return (
    <View style={styles.wrap}>
      <TouchableOpacity
        style={[styles.primaryButton, primaryDisabled && styles.primaryButtonDisabled]}
        onPress={onPrimaryPress}
        activeOpacity={0.8}
        disabled={primaryDisabled || primaryLoading}
      >
        {primaryLoading ? (
          <ActivityIndicator color="#ffffff" />
        ) : (
          <>
            {primaryIconName ? (
              <Icon name={primaryIconName} size={18} color="#ffffff" style={styles.primaryButtonIcon} />
            ) : null}
            <Text style={styles.primaryButtonText}>{primaryLabel}</Text>
          </>
        )}
      </TouchableOpacity>

      {secondaryLabel && onSecondaryPress ? (
        <TouchableOpacity style={styles.ghostButton} onPress={onSecondaryPress} activeOpacity={0.7}>
          <Text style={styles.ghostButtonText}>{secondaryLabel}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: {
    marginHorizontal: 22,
  },
  primaryButton: {
    marginTop: 12,
    backgroundColor: '#059669',
    borderRadius: 16,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#059669',
    shadowOpacity: 0.26,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  primaryButtonDisabled: {
    opacity: 0.7,
  },
  primaryButtonIcon: {
    marginRight: 8,
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#ffffff',
  },
  ghostButton: {
    marginTop: 12,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
  },
  ghostButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#1f2937',
  },
});
