import React, { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  TouchableOpacity, 
  TextInput, 
  Platform, 
  Modal, 
  Image, 
  RefreshControl, 
  ActivityIndicator, 
  SectionList, 
  Alert, 
  Linking,
  Animated,
  Dimensions,
  Vibration,
} from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import ContactService, { contactService } from '../services/contactService';
import { ContactPermissionModal } from '../components/ContactPermissionModal';
import { useContactNames } from '../hooks/useContactName';
import { useApolloClient, useMutation, gql } from '@apollo/client';
import { EnhancedContactCard } from '../components/EnhancedContactCard';
import { FloatingActionButton } from '../components/FloatingActionButton';
import { AlphabetIndex } from '../components/AlphabetIndex';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import * as Keychain from 'react-native-keychain';

type ContactsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
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

const { width } = Dimensions.get('window');

// Recent contacts storage keys
const RECENT_CONTACTS_SERVICE = 'com.confio.recentcontacts';
const RECENT_CONTACTS_KEY = 'recent_contacts';

export const ContactsScreenV2 = () => {
  const navigation = useNavigation<ContactsScreenNavigationProp>();
  const apolloClient = useApolloClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [showTokenSelection, setShowTokenSelection] = useState(false);
  const [selectedFriend, setSelectedFriend] = useState<any>(null);
  const [showPermissionModal, setShowPermissionModal] = useState(false);
  const [isLoadingContacts, setIsLoadingContacts] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [hasContactPermission, setHasContactPermission] = useState<boolean | null>(null);
  const [recentContacts, setRecentContacts] = useState<string[]>([]);
  const [filterMode, setFilterMode] = useState<'all' | 'confio' | 'invite'>('all');
  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const sectionListRef = useRef<SectionList>(null);
  const filterAnimation = useRef(new Animated.Value(0)).current;
  
  const [contactsData, setContactsData] = useState<{
    friends: any[];
    nonConfioFriends: any[];
    allContacts: any[];
    isLoaded: boolean;
  }>({ friends: [], nonConfioFriends: [], allContacts: [], isLoaded: false });

  // Load recent contacts
  useEffect(() => {
    loadRecentContacts();
  }, []);

  const loadRecentContacts = async () => {
    try {
      const credentials = await Keychain.getInternetCredentials(RECENT_CONTACTS_SERVICE);
      if (credentials && credentials.password) {
        const recentData = JSON.parse(credentials.password);
        setRecentContacts(recentData);
      }
    } catch (error) {
      console.error('Error loading recent contacts:', error);
    }
  };

  const saveRecentContact = async (contactId: string) => {
    try {
      let recent = [...recentContacts];
      recent = recent.filter(id => id !== contactId);
      recent.unshift(contactId);
      recent = recent.slice(0, 5); // Keep only 5 recent
      setRecentContacts(recent);
      await Keychain.setInternetCredentials(
        RECENT_CONTACTS_SERVICE,
        RECENT_CONTACTS_KEY,
        JSON.stringify(recent)
      );
    } catch (error) {
      console.error('Error saving recent contact:', error);
    }
  };

  // Check contact permission on mount
  useEffect(() => {
    checkContactPermission();
  }, []);

  const checkContactPermission = async () => {
    try {
      const hasPermission = await contactService.hasContactPermission();
      setHasContactPermission(hasPermission);
      
      if (hasPermission) {
        const contacts = await contactService.getAllContacts();
        if (contacts.length > 0) {
          await displayContacts(contacts);
        }
      } else {
        const storedStatus = await contactService.getStoredPermissionStatus();
        if (!storedStatus || storedStatus === 'pending') {
          setShowPermissionModal(true);
        }
      }
    } catch (error) {
      console.error('Error checking contact permission:', error);
    }
  };

  const displayContacts = async (allContacts: any[]) => {
    if (allContacts.length === 0) {
      setContactsData({ friends: [], nonConfioFriends: [], allContacts: [], isLoaded: true });
      return;
    }
    
    const formattedContacts = allContacts.map((contact, index) => ({
      id: contact.isOnConfio && contact.confioUserId ? contact.confioUserId : `contact_${index}`,
      name: contact.name || 'Sin nombre',
      avatar: contact.name ? contact.name.charAt(0).toUpperCase() : '?',
      phone: contact.phoneNumbers && contact.phoneNumbers[0] ? contact.phoneNumbers[0] : '',
      isOnConfio: contact.isOnConfio || false,
      userId: contact.confioUserId || null,
      aptosAddress: contact.confioSuiAddress || null
    }));
    
    const confioUsers = formattedContacts.filter(contact => contact.isOnConfio);
    const nonConfioUsers = formattedContacts.filter(contact => !contact.isOnConfio);
    
    setContactsData({
      friends: confioUsers,
      nonConfioFriends: nonConfioUsers,
      allContacts: allContacts,
      isLoaded: true
    });
  };

  // Filter animation
  useEffect(() => {
    Animated.timing(filterAnimation, {
      toValue: showFilterMenu ? 1 : 0,
      duration: 200,
      useNativeDriver: true,
    }).start();
  }, [showFilterMenu]);

  // Get filtered contacts based on search and filter mode
  const getFilteredContacts = useCallback(() => {
    let contacts = [];
    
    switch (filterMode) {
      case 'confio':
        contacts = contactsData.friends;
        break;
      case 'invite':
        contacts = contactsData.nonConfioFriends;
        break;
      default:
        contacts = [...contactsData.friends, ...contactsData.nonConfioFriends];
    }
    
    if (searchTerm) {
      contacts = contacts.filter(contact =>
        contact.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        contact.phone.includes(searchTerm)
      );
    }
    
    return contacts;
  }, [contactsData, searchTerm, filterMode]);

  // Group contacts by letter with recent section
  const sections = useMemo(() => {
    const filtered = getFilteredContacts();
    const groups: { [key: string]: any[] } = {};
    const sectionData = [];
    
    // Add recent contacts section
    if (!searchTerm && filterMode === 'all' && recentContacts.length > 0) {
      const recentContactsData = recentContacts
        .map(id => filtered.find(c => c.id === id))
        .filter(Boolean)
        .slice(0, 3);
      
      if (recentContactsData.length > 0) {
        sectionData.push({
          title: 'Recientes',
          data: recentContactsData,
          isRecent: true,
        });
      }
    }
    
    // Group by first letter
    filtered.forEach(contact => {
      const firstLetter = contact.name.charAt(0).toUpperCase();
      if (!groups[firstLetter]) {
        groups[firstLetter] = [];
      }
      groups[firstLetter].push(contact);
    });
    
    // Convert to sections
    Object.keys(groups)
      .sort()
      .forEach(letter => {
        sectionData.push({
          title: letter,
          data: groups[letter],
        });
      });
    
    return sectionData;
  }, [getFilteredContacts, searchTerm, filterMode, recentContacts]);

  // Get alphabet letters
  const alphabetLetters = useMemo(() => {
    return sections
      .filter(section => section.title !== 'Recientes')
      .map(section => section.title);
  }, [sections]);

  const handleLetterPress = (letter: string) => {
    const sectionIndex = sections.findIndex(section => section.title === letter);
    if (sectionIndex !== -1 && sectionListRef.current) {
      sectionListRef.current.scrollToLocation({
        sectionIndex,
        itemIndex: 0,
        viewOffset: 0,
        animated: true,
      });
    }
  };

  const handleContactPress = (contact: any) => {
    // Haptic feedback
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }
    
    saveRecentContact(contact.id);
    
    navigation.navigate('FriendDetail', {
      friendId: contact.userId || contact.id,
      friendName: contact.name,
      friendAvatar: contact.avatar,
      friendPhone: contact.phone,
      isOnConfio: contact.isOnConfio || false
    });
  };

  const handleSendToFriend = (contact: any) => {
    setSelectedFriend(contact);
    setShowTokenSelection(true);
  };

  const handleInviteFriend = (contact: any) => {
    setSelectedFriend(contact);
    setShowTokenSelection(true);
  };

  const handleFABSend = () => {
    navigation.navigate('SendWithAddress', { tokenType: 'cusd' });
  };

  const handleFABReceive = () => {
    navigation.navigate('USDCDeposit', { tokenType: 'cusd' });
  };

  const handleFABScan = () => {
    // Navigate to scan screen
    navigation.navigate('BottomTabs', { screen: 'Scan' });
  };

  const renderSectionHeader = ({ section }) => (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{section.title}</Text>
      {section.isRecent && (
        <TouchableOpacity onPress={async () => {
          setRecentContacts([]);
          try {
            await Keychain.resetInternetCredentials(RECENT_CONTACTS_SERVICE);
          } catch (error) {
            console.error('Error clearing recent contacts:', error);
          }
        }}>
          <Text style={styles.clearButton}>Limpiar</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const renderItem = ({ item, section }) => (
    <EnhancedContactCard
      contact={item}
      onPress={() => handleContactPress(item)}
      onSendPress={() => handleSendToFriend(item)}
      onInvitePress={() => handleInviteFriend(item)}
      isRecent={section.isRecent}
    />
  );

  const ListEmptyComponent = () => (
    <View style={styles.emptyState}>
      <View style={styles.emptyIcon}>
        <Svg height="100%" width="100%" style={StyleSheet.absoluteFillObject}>
          <Defs>
            <LinearGradient id="emptyGrad" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor="#F3F4F6" />
              <Stop offset="1" stopColor="#E5E7EB" />
            </LinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#emptyGrad)" rx="60" />
        </Svg>
        <Icon name="users" size={48} color="#9CA3AF" />
      </View>
      <Text style={styles.emptyTitle}>
        {searchTerm ? 'No se encontraron contactos' : 'No hay contactos'}
      </Text>
      <Text style={styles.emptyDescription}>
        {searchTerm 
          ? `No hay contactos que coincidan con "${searchTerm}"`
          : hasContactPermission === false 
            ? 'Permite el acceso a tus contactos para comenzar'
            : 'Sincroniza tus contactos para empezar a enviar dinero'
        }
      </Text>
      {!searchTerm && hasContactPermission !== false && (
        <TouchableOpacity style={styles.syncButton} onPress={handleRefresh}>
          <Icon name="refresh-cw" size={20} color="#fff" />
          <Text style={styles.syncButtonText}>Sincronizar contactos</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    // Refresh logic here
    setRefreshing(false);
  };

  return (
    <>
      <View style={styles.container}>
        {/* Header with search and filters */}
        <View style={styles.header}>
          <View style={styles.searchContainer}>
            <Icon name="search" size={20} color="#9CA3AF" />
            <TextInput
              style={styles.searchInput}
              placeholder="Buscar contactos..."
              placeholderTextColor="#9CA3AF"
              value={searchTerm}
              onChangeText={setSearchTerm}
            />
            <TouchableOpacity 
              style={styles.filterButton}
              onPress={() => setShowFilterMenu(!showFilterMenu)}
            >
              <Icon 
                name="filter" 
                size={20} 
                color={filterMode !== 'all' ? colors.primary : '#6B7280'} 
              />
              {filterMode !== 'all' && <View style={styles.filterDot} />}
            </TouchableOpacity>
          </View>
          
          {/* Filter chips */}
          <Animated.View 
            style={[
              styles.filterChips,
              {
                opacity: filterAnimation,
                transform: [
                  {
                    translateY: filterAnimation.interpolate({
                      inputRange: [0, 1],
                      outputRange: [-20, 0],
                    }),
                  },
                ],
              },
            ]}
          >
            <TouchableOpacity
              style={[styles.chip, filterMode === 'all' && styles.chipActive]}
              onPress={() => setFilterMode('all')}
            >
              <Text style={[styles.chipText, filterMode === 'all' && styles.chipTextActive]}>
                Todos
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.chip, filterMode === 'confio' && styles.chipActive]}
              onPress={() => setFilterMode('confio')}
            >
              <Icon name="check-circle" size={14} color={filterMode === 'confio' ? '#fff' : '#6B7280'} />
              <Text style={[styles.chipText, filterMode === 'confio' && styles.chipTextActive]}>
                En Confío
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.chip, filterMode === 'invite' && styles.chipActive]}
              onPress={() => setFilterMode('invite')}
            >
              <Icon name="gift" size={14} color={filterMode === 'invite' ? '#fff' : '#6B7280'} />
              <Text style={[styles.chipText, filterMode === 'invite' && styles.chipTextActive]}>
                Por invitar
              </Text>
            </TouchableOpacity>
          </Animated.View>
        </View>

        {/* Contacts list */}
        <SectionList
          ref={sectionListRef}
          sections={sections}
          renderItem={renderItem}
          renderSectionHeader={renderSectionHeader}
          ListEmptyComponent={ListEmptyComponent}
          keyExtractor={(item, index) => item.id || `contact-${index}`}
          contentContainerStyle={styles.listContent}
          stickySectionHeadersEnabled={true}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={colors.primary}
            />
          }
        />

        {/* Alphabet index */}
        {alphabetLetters.length > 10 && (
          <AlphabetIndex
            letters={alphabetLetters}
            onLetterPress={handleLetterPress}
          />
        )}

        {/* Floating Action Button */}
        <FloatingActionButton
          onSendPress={handleFABSend}
          onReceivePress={handleFABReceive}
          onScanPress={handleFABScan}
        />
      </View>

      {/* Token Selection Modal */}
      <Modal
        visible={showTokenSelection}
        transparent
        animationType="slide"
        onRequestClose={() => setShowTokenSelection(false)}
      >
        {/* Modal content here */}
      </Modal>

      {/* Contact Permission Modal */}
      <ContactPermissionModal
        visible={showPermissionModal}
        onAllow={() => {}}
        onDeny={() => {}}
        onClose={() => setShowPermissionModal(false)}
      />
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    backgroundColor: '#FFFFFF',
    paddingTop: Platform.OS === 'ios' ? 50 : 30,
    paddingHorizontal: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 3,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 12,
  },
  searchInput: {
    flex: 1,
    fontSize: 16,
    color: '#1F2937',
  },
  filterButton: {
    position: 'relative',
  },
  filterDot: {
    position: 'absolute',
    top: -2,
    right: -2,
    width: 6,
    height: 6,
    backgroundColor: colors.primary,
    borderRadius: 3,
  },
  filterChips: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 12,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: '#F3F4F6',
    gap: 6,
  },
  chipActive: {
    backgroundColor: colors.primary,
  },
  chipText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
  },
  chipTextActive: {
    color: '#FFFFFF',
  },
  listContent: {
    paddingBottom: 100,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: '#F9FAFB',
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    letterSpacing: 0.5,
  },
  clearButton: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '500',
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 80,
    paddingHorizontal: 32,
  },
  emptyIcon: {
    width: 120,
    height: 120,
    borderRadius: 60,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  emptyDescription: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 24,
  },
  syncButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 24,
    gap: 8,
  },
  syncButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});