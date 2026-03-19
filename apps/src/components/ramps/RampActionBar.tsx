import React from 'react';
import {
  ActivityIndicator,
  Platform,
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
    <View style={styles.surface}>
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
    </View>
  );
};

const styles = StyleSheet.create({
  surface: {
    marginTop: 8,
    marginHorizontal: 16,
    marginBottom: 8,
    backgroundColor: '#ffffff',
    borderRadius: 24,
    paddingHorizontal: 6,
    paddingTop: 10,
    paddingBottom: Platform.OS === 'ios' ? 6 : 10,
    shadowColor: '#10b981',
    shadowOpacity: 0.10,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: -4 },
    elevation: 8,
    borderWidth: 1,
    borderColor: '#e8f5ee',
  },
  wrap: {
    marginHorizontal: 10,
  },
  primaryButton: {
    marginTop: 4,
    backgroundColor: '#059669',
    borderRadius: 16,
    paddingVertical: 17,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#059669',
    shadowOpacity: 0.30,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 5,
  },
  primaryButtonDisabled: {
    opacity: 0.6,
  },
  primaryButtonIcon: {
    marginRight: 8,
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '800',
    color: '#ffffff',
    letterSpacing: 0.2,
  },
  ghostButton: {
    marginTop: 10,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 13,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#d1fae5',
    backgroundColor: '#f0fdf4',
  },
  ghostButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#047857',
  },
});
