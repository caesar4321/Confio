import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  Image,
  Dimensions,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

const { width: screenWidth } = Dimensions.get('window');

interface PioneroBadgeModalProps {
  visible: boolean;
  onClose: () => void;
  achievement: {
    name: string;
    description: string;
    confioReward: number;
    status: string;
  };
}

export const PioneroBadgeModal: React.FC<PioneroBadgeModalProps> = ({
  visible,
  onClose,
  achievement,
}) => {
  const isPending = achievement.status?.toLowerCase() === 'pending';
  
  return (
    <Modal
      visible={visible}
      animationType="fade"
      transparent={true}
      onRequestClose={onClose}
    >
      <TouchableOpacity 
        style={styles.modalOverlay} 
        activeOpacity={1} 
        onPress={onClose}
      >
        <View style={styles.modalContent} onStartShouldSetResponder={() => true}>
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Icon name="x" size={24} color="#666" />
          </TouchableOpacity>
          
          <Image 
            source={require('../assets/png/PioneroBeta.png')} 
            style={styles.largeBadge}
            resizeMode="contain"
          />
          
          <Text style={styles.achievementName}>{achievement.name}</Text>
          <Text style={styles.achievementDescription}>{achievement.description}</Text>
          
          <View style={styles.rewardContainer}>
            <Icon name="gift" size={20} color="#FFD700" />
            <Text style={styles.rewardText}>{achievement.confioReward} $CONFIO</Text>
          </View>
          
          {isPending ? (
            <View style={styles.statusContainer}>
              <Icon name="lock" size={16} color="#999" />
              <Text style={styles.pendingText}>Por desbloquear</Text>
            </View>
          ) : (
            <View style={styles.statusContainer}>
              <Icon name="check-circle" size={16} color="#00b894" />
              <Text style={styles.earnedText}>¡Ya eres Pionero Beta!</Text>
            </View>
          )}
          
          <View style={styles.exclusiveContainer}>
            <Text style={styles.exclusiveText}>🏆 Exclusivo para los primeros 10.000 usuarios</Text>
          </View>
        </View>
      </TouchableOpacity>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#FFF8DC',
    borderRadius: 20,
    padding: 24,
    width: screenWidth * 0.85,
    maxWidth: 360,
    alignItems: 'center',
    borderWidth: 3,
    borderColor: '#FFD700',
    shadowColor: '#FFD700',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 10,
  },
  closeButton: {
    position: 'absolute',
    top: 12,
    right: 12,
    padding: 8,
    zIndex: 1,
  },
  largeBadge: {
    width: 180,
    height: 180,
    marginBottom: 20,
  },
  achievementName: {
    fontSize: 28,
    fontWeight: '800',
    color: '#8B4513',
    marginBottom: 8,
    textAlign: 'center',
  },
  achievementDescription: {
    fontSize: 16,
    color: '#666',
    textAlign: 'center',
    marginBottom: 20,
    lineHeight: 22,
  },
  rewardContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#fff',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 20,
    marginBottom: 16,
  },
  rewardText: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFD700',
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 20,
  },
  pendingText: {
    fontSize: 14,
    color: '#999',
    fontWeight: '600',
  },
  earnedText: {
    fontSize: 14,
    color: '#00b894',
    fontWeight: '600',
  },
  exclusiveContainer: {
    backgroundColor: 'rgba(255, 215, 0, 0.2)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#FFD700',
  },
  exclusiveText: {
    fontSize: 13,
    color: '#8B4513',
    fontWeight: '600',
    textAlign: 'center',
  },
});