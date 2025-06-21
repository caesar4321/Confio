import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView, Platform, Modal, Image } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

type ContactsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#059669',
  secondary: '#8b5cf6',
  secondaryText: '#8b5cf6',
  accent: '#3b82f6',
  accentText: '#3b82f6',
  violet: '#8b5cf6',
  violetText: '#8b5cf6',
  violetLight: '#f5f3ff',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
};

export const ContactsScreen = () => {
  const navigation = useNavigation<ContactsScreenNavigationProp>();
  const [searchTerm, setSearchTerm] = useState('');
  const [showTokenSelection, setShowTokenSelection] = useState(false);
  const [showSendTokenSelection, setShowSendTokenSelection] = useState(false);
  const [showFriendTokenSelection, setShowFriendTokenSelection] = useState(false);
  const [selectedFriend, setSelectedFriend] = useState<any>(null);
  
  // Mock data
  const friends = [
    { name: "Evelyn", isOnConfio: true, avatar: "E", phone: "+58 412-123-4567" },
    { name: "Julian", isOnConfio: true, avatar: "J", phone: "+58 414-987-6543" },
    { name: "Olivia", isOnConfio: true, avatar: "O", phone: "+58 416-555-1234" },
    { name: "Susy", isOnConfio: true, avatar: "S", phone: "+58 418-777-8888" }
  ];

  const nonConfioFriends = [
    { name: "Boris", avatar: "B", phone: "+58 412-111-2222" },
    { name: "Jeffrey", avatar: "J", phone: "+58 414-333-4444" },
    { name: "Juan", avatar: "J", phone: "+58 416-555-6666" },
    { name: "Yadira", avatar: "Y", phone: "+58 418-999-0000" }
  ];

  const handleReceiveWithAddress = () => {
    setShowTokenSelection(true);
  };

  const handleTokenSelection = (tokenType: 'cusd' | 'confio') => {
    setShowTokenSelection(false);
    navigation.navigate('USDCDeposit', { tokenType });
  };

  const handleSendWithAddress = () => {
    setShowSendTokenSelection(true);
  };

  const handleSendTokenSelection = (tokenType: 'cusd' | 'confio') => {
    setShowSendTokenSelection(false);
    navigation.navigate('SendWithAddress', { tokenType });
  };

  const handleSendToFriend = (friend: any) => {
    console.log('ContactsScreen: handleSendToFriend called with friend:', friend.name);
    setSelectedFriend(friend);
    setShowFriendTokenSelection(true);
  };

  const handleFriendTokenSelection = (tokenType: 'cusd' | 'confio') => {
    console.log('ContactsScreen: handleFriendTokenSelection called with tokenType:', tokenType);
    console.log('ContactsScreen: selectedFriend:', selectedFriend);
    setShowFriendTokenSelection(false);
    navigation.navigate('SendToFriend', { friend: selectedFriend, tokenType });
  };

  const handleInviteFriend = (friend: any) => {
    console.log('ContactsScreen: handleInviteFriend called with friend:', friend.name);
    // For non-Confío friends, we can still send them money with an invitation
    setSelectedFriend(friend);
    setShowFriendTokenSelection(true);
  };

  // Filter friends based on search term
  const filteredConfioFriends = friends.filter(friend =>
    friend.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    friend.phone.includes(searchTerm)
  );

  const filteredNonConfioFriends = nonConfioFriends.filter(friend =>
    friend.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    friend.phone.includes(searchTerm)
  );

  const ContactCard = ({ contact, isOnConfio = false }: { contact: any; isOnConfio?: boolean }) => (
    <View style={styles.contactCard}>
      <View style={[
        styles.avatarContainer,
        { backgroundColor: isOnConfio ? colors.primaryLight : '#e5e7eb' }
      ]}>
        <Text style={[
          styles.avatarText,
          { color: isOnConfio ? colors.primaryDark : '#6b7280' }
        ]}>
          {contact.avatar}
        </Text>
      </View>
      
      <View style={styles.contactInfo}>
        <Text style={styles.contactName}>{contact.name}</Text>
        <Text style={styles.contactPhone}>{contact.phone}</Text>
      </View>
      
      {isOnConfio ? (
        <TouchableOpacity
          style={styles.sendButton}
          onPress={() => handleSendToFriend(contact)}
        >
          <Icon name="send" size={20} color="#fff" />
        </TouchableOpacity>
      ) : (
        <TouchableOpacity
          style={styles.inviteButton}
          onPress={() => handleInviteFriend(contact)}
        >
          <Icon name="gift" size={16} color="#fff" style={{ marginRight: 6 }} />
          <Text style={styles.inviteButtonText}>Enviar & Invitar</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const TokenSelectionModal = () => (
    <Modal
      visible={showTokenSelection}
      transparent
      animationType="fade"
      onRequestClose={() => setShowTokenSelection(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Selecciona el token</Text>
            <TouchableOpacity onPress={() => setShowTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          
          <Text style={styles.modalSubtitle}>
            ¿Qué token quieres recibir?
          </Text>

          <View style={styles.tokenOptions}>
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleTokenSelection('cusd')}
            >
              <View style={styles.tokenInfo}>
                <Image source={cUSDLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Dollar</Text>
                  <Text style={styles.tokenSymbol}>$cUSD</Text>
                  <Text style={styles.tokenDescription}>
                    Moneda estable para pagos diarios
                  </Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleTokenSelection('confio')}
            >
              <View style={styles.tokenInfo}>
                <Image source={CONFIOLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Token</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>
                    Token de gobernanza y utilidad
                  </Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>

          <TouchableOpacity 
            style={styles.cancelButton}
            onPress={() => setShowTokenSelection(false)}
          >
            <Text style={styles.cancelButtonText}>Cancelar</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );

  const SendTokenSelectionModal = () => (
    <Modal
      visible={showSendTokenSelection}
      transparent
      animationType="fade"
      onRequestClose={() => setShowSendTokenSelection(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Selecciona el token</Text>
            <TouchableOpacity onPress={() => setShowSendTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.modalSubtitle}>¿Qué token quieres enviar?</Text>
          <View style={styles.tokenOptions}>
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleSendTokenSelection('cusd')}
            >
              <View style={styles.tokenInfo}>
                <Image source={cUSDLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Dollar</Text>
                  <Text style={styles.tokenSymbol}>$cUSD</Text>
                  <Text style={styles.tokenDescription}>Moneda estable para pagos diarios</Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleSendTokenSelection('confio')}
            >
              <View style={styles.tokenInfo}>
                <Image source={CONFIOLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Token</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>Token de gobernanza y utilidad</Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <TouchableOpacity 
            style={styles.cancelButton}
            onPress={() => setShowSendTokenSelection(false)}
          >
            <Text style={styles.cancelButtonText}>Cancelar</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );

  const FriendTokenSelectionModal = () => (
    <Modal
      visible={showFriendTokenSelection}
      transparent
      animationType="fade"
      onRequestClose={() => setShowFriendTokenSelection(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Selecciona el token</Text>
            <TouchableOpacity onPress={() => setShowFriendTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.modalSubtitle}>¿Qué token quieres enviar a {selectedFriend?.name}?</Text>
          <View style={styles.tokenOptions}>
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleFriendTokenSelection('cusd')}
            >
              <View style={styles.tokenInfo}>
                <Image source={cUSDLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Dollar</Text>
                  <Text style={styles.tokenSymbol}>$cUSD</Text>
                  <Text style={styles.tokenDescription}>Moneda estable para pagos diarios</Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleFriendTokenSelection('confio')}
            >
              <View style={styles.tokenInfo}>
                <Image source={CONFIOLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Token</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>Token de gobernanza y utilidad</Text>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <TouchableOpacity 
            style={styles.cancelButton}
            onPress={() => setShowFriendTokenSelection(false)}
          >
            <Text style={styles.cancelButtonText}>Cancelar</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );

  return (
    <ScrollView 
      style={styles.container} 
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ paddingBottom: 24 }}
    >
      {/* Search Bar */}
      <View style={styles.searchSection}>
        <View style={styles.searchBar}>
          <Icon name="search" size={20} color="#9ca3af" style={styles.searchIcon} />
          <TextInput 
            style={styles.searchInput}
            placeholder="Buscar contactos..." 
            placeholderTextColor="#6b7280"
            value={searchTerm}
            onChangeText={setSearchTerm}
          />
        </View>
      </View>

      {/* Send/Receive Options */}
      <View style={styles.actionSection}>
        <View style={styles.actionButtons}>
          <TouchableOpacity 
            style={styles.actionButton}
            onPress={handleSendWithAddress}
          >
            <View style={styles.actionButtonContent}>
              <View style={styles.actionIconContainer}>
                <Icon name="send" size={20} color="#fff" />
              </View>
              <View style={styles.actionTextContainer}>
                <Text style={styles.actionButtonTitle}>Enviar con dirección</Text>
                <Text style={styles.actionButtonSubtitle}>Envía a cualquier wallet</Text>
              </View>
            </View>
            <Icon name="chevron-right" size={20} color="#9ca3af" />
          </TouchableOpacity>
          
          <TouchableOpacity 
            style={styles.actionButton}
            onPress={handleReceiveWithAddress}
          >
            <View style={styles.actionButtonContent}>
              <View style={styles.actionIconContainer}>
                <Icon name="download" size={20} color="#fff" />
              </View>
              <View style={styles.actionTextContainer}>
                <Text style={styles.actionButtonTitle}>Recibir con dirección</Text>
                <Text style={styles.actionButtonSubtitle}>Comparte tu dirección</Text>
              </View>
            </View>
            <Icon name="chevron-right" size={20} color="#9ca3af" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Friends on Confío */}
      {filteredConfioFriends.length > 0 && (
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Amigos en Confío</Text>
            <View style={styles.sectionCount}>
              <Text style={styles.sectionCountText}>{filteredConfioFriends.length}</Text>
            </View>
          </View>
          
          <View style={styles.contactsList}>
            {filteredConfioFriends.map((friend, index) => (
              <ContactCard key={index} contact={friend} isOnConfio={true} />
            ))}
          </View>
        </View>
      )}

      {/* Friends not on Confío */}
      {filteredNonConfioFriends.length > 0 && (
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Invita a tus amigos</Text>
            <View style={styles.sectionCount}>
              <Text style={styles.sectionCountText}>{filteredNonConfioFriends.length}</Text>
            </View>
          </View>
          
          {/* Info Card */}
          <View style={styles.infoCard}>
            <View style={styles.infoCardContent}>
              <View style={styles.infoIconContainer}>
                <Icon name="clock" size={16} color="#fff" />
              </View>
              <View style={styles.infoTextContainer}>
                <Text style={styles.infoTitle}>Envío con invitación</Text>
                <Text style={styles.infoDescription}>
                  Envía dinero y tu amigo recibirá una invitación por WhatsApp. 
                  Tendrá <Text style={styles.infoBold}>7 días</Text> para crear su cuenta y reclamar el dinero.
                </Text>
              </View>
            </View>
          </View>
          
          <View style={styles.contactsList}>
            {filteredNonConfioFriends.map((friend, index) => (
              <ContactCard key={index} contact={friend} isOnConfio={false} />
            ))}
          </View>
        </View>
      )}

      {/* Empty State */}
      {filteredConfioFriends.length === 0 && filteredNonConfioFriends.length === 0 && searchTerm && (
        <View style={styles.emptyState}>
          <View style={styles.emptyIconContainer}>
            <Icon name="users" size={32} color="#9ca3af" />
          </View>
          <Text style={styles.emptyTitle}>No se encontraron contactos</Text>
          <Text style={styles.emptyDescription}>
            No hay contactos que coincidan con "{searchTerm}"
          </Text>
        </View>
      )}

      <TokenSelectionModal />
      <SendTokenSelectionModal />
      <FriendTokenSelectionModal />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  searchSection: {
    paddingHorizontal: 16,
    paddingTop: 24,
    paddingBottom: 12,
    backgroundColor: '#fff',
  },
  searchBar: {
    backgroundColor: '#f9fafb',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 16,
  },
  searchIcon: {
    marginRight: 12,
  },
  searchInput: {
    flex: 1,
    fontSize: 16,
    color: '#1f2937',
  },
  actionSection: {
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  actionButtons: {
    gap: 8,
  },
  actionButton: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    paddingVertical: 16,
    paddingHorizontal: 16,
  },
  actionButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionIconContainer: {
    backgroundColor: colors.primary,
    padding: 12,
    borderRadius: 999,
    marginRight: 16,
  },
  actionTextContainer: {
    flex: 1,
  },
  actionButtonTitle: {
    fontWeight: '500',
    color: '#1f2937',
    fontSize: 16,
  },
  actionButtonSubtitle: {
    fontSize: 13,
    color: '#6b7280',
  },
  section: {
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#6b7280',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  sectionCount: {
    backgroundColor: '#f3f4f6',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  sectionCountText: {
    fontSize: 11,
    color: '#9ca3af',
  },
  contactsList: {
    gap: 2,
  },
  contactCard: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  avatarContainer: {
    width: 48,
    height: 48,
    borderRadius: 24,
    marginRight: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontWeight: '500',
    fontSize: 18,
  },
  contactInfo: {
    flex: 1,
  },
  contactName: {
    fontWeight: '500',
    color: '#1f2937',
    fontSize: 16,
  },
  contactPhone: {
    fontSize: 13,
    color: '#6b7280',
  },
  sendButton: {
    backgroundColor: colors.primary,
    padding: 12,
    borderRadius: 999,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  inviteButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.violet,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
  },
  inviteButtonText: {
    color: '#fff',
    fontWeight: '500',
    fontSize: 14,
  },
  infoCard: {
    backgroundColor: colors.violetLight,
    borderColor: colors.violet,
    borderWidth: 1,
    padding: 16,
    borderRadius: 16,
    marginBottom: 12,
  },
  infoCardContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  infoIconContainer: {
    backgroundColor: colors.violet,
    padding: 8,
    borderRadius: 999,
    marginRight: 12,
    marginTop: 2,
  },
  infoTextContainer: {
    flex: 1,
  },
  infoTitle: {
    fontWeight: '500',
    color: '#6d28d9',
    marginBottom: 4,
  },
  infoDescription: {
    fontSize: 13,
    color: '#7c3aed',
    lineHeight: 18,
  },
  infoBold: {
    fontWeight: 'bold',
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
    paddingVertical: 40,
  },
  emptyIconContainer: {
    width: 64,
    height: 64,
    backgroundColor: '#f3f4f6',
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  emptyTitle: {
    fontWeight: '500',
    color: '#1f2937',
    marginBottom: 8,
    fontSize: 16,
  },
  emptyDescription: {
    fontSize: 13,
    color: '#6b7280',
    textAlign: 'center',
    maxWidth: 240,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 20,
    padding: 24,
    width: '100%',
    maxWidth: 400,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.25,
        shadowRadius: 8,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#1F2937',
  },
  modalSubtitle: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 24,
    lineHeight: 20,
  },
  tokenOptions: {
    gap: 12,
    marginBottom: 8,
  },
  tokenOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#F9FAFB',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  tokenInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  tokenLogo: {
    width: 48,
    height: 48,
    borderRadius: 24,
    marginRight: 16,
  },
  tokenDetails: {
    flex: 1,
  },
  tokenName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 2,
  },
  tokenSymbol: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginBottom: 4,
  },
  tokenDescription: {
    fontSize: 12,
    color: '#6B7280',
    lineHeight: 16,
  },
  cancelButton: {
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 16,
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#6B7280',
  },
}); 