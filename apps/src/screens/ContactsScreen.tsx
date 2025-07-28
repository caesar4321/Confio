import React, { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Platform, Modal, Image, RefreshControl, ActivityIndicator, SectionList, Alert, Linking } from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import ContactService, { contactService } from '../services/contactService';
import { ContactPermissionModal } from '../components/ContactPermissionModal';
import { InviteEmployeeModal } from '../components/InviteEmployeeModal';
import { useContactNames } from '../hooks/useContactName';
import { useApolloClient, useMutation, gql, useQuery } from '@apollo/client';
import { useAccount } from '../contexts/AccountContext';
import { INVITE_EMPLOYEE, GET_CURRENT_BUSINESS_EMPLOYEES, GET_CURRENT_BUSINESS_INVITATIONS, CANCEL_INVITATION } from '../apollo/queries';
import { getCountryByIso } from '../utils/countries';

// Utility function to format phone number with country code
const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  
  // If we have a country code, format it
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1]; // country[1] is the phone code (e.g., '+54')
      return `${countryCode} ${phoneNumber}`;
    }
  }
  
  return phoneNumber;
};

type ContactsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

// Test mutation to create users (only in DEBUG mode)
const CREATE_TEST_USERS = gql`
  mutation CreateTestUsers($phoneNumbers: [String!]!) {
    createTestUsers(phoneNumbers: $phoneNumbers) {
      success
      error
      createdCount
      usersCreated {
        phoneNumber
        userId
        username
        firstName
        lastName
        isOnConfio
        activeAccountId
        activeAccountSuiAddress
      }
    }
  }
`;

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

// Memoized ContactCard component moved outside to prevent recreation
interface ContactCardProps {
  contact: any;
  isOnConfio?: boolean;
  onPress: (contact: any) => void;
  onSendPress: (contact: any) => void;
  onInvitePress: (contact: any) => void;
}

interface EmployeeCardProps {
  contact: any;
  onPress: (contact: any) => void;
  onRemove: (contact: any) => void;
  onCancelInvitation: (contact: any) => void;
}

const getRoleLabel = (role: string) => {
  switch (role) {
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role;
  }
};

const EmployeeCard = memo(({ contact, onPress, onRemove, onCancelInvitation }: EmployeeCardProps) => {
  const isInvitation = contact.isInvitation;
  const role = getRoleLabel(contact.role);
  
  return (
    <TouchableOpacity style={styles.contactCard} onPress={() => onPress(contact)}>
      <View style={[
        styles.avatarContainer,
        { backgroundColor: isInvitation ? '#fef3c7' : colors.primaryLight }
      ]}>
        <Text style={[
          styles.avatarText,
          { color: isInvitation ? '#f59e0b' : colors.primaryDark }
        ]}>
          {contact.avatar}
        </Text>
      </View>
      
      <View style={styles.contactInfo}>
        <Text style={styles.contactName}>{contact.name}</Text>
        <Text style={styles.contactPhone}>{contact.phone}</Text>
        <Text style={styles.employeeRole}>{role}</Text>
      </View>
      
      <View style={styles.employeeActionContainer}>
        {isInvitation ? (
          <TouchableOpacity
            style={styles.cancelButton}
            onPress={(e) => {
              e.stopPropagation();
              onCancelInvitation(contact);
            }}
          >
            <Icon name="x" size={20} color="#ef4444" />
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={styles.moreButton}
            onPress={(e) => {
              e.stopPropagation();
              onRemove(contact);
            }}
          >
            <Icon name="more-vertical" size={20} color="#6b7280" />
          </TouchableOpacity>
        )}
      </View>
    </TouchableOpacity>
  );
});

const ContactCard = memo(({ contact, isOnConfio = false, onPress, onSendPress, onInvitePress }: ContactCardProps) => (
  <TouchableOpacity style={styles.contactCard} onPress={() => onPress(contact)}>
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
        onPress={(e) => {
          e.stopPropagation();
          onSendPress(contact);
        }}
      >
        <Icon name="send" size={20} color="#fff" />
      </TouchableOpacity>
    ) : (
      <TouchableOpacity
        style={styles.inviteButton}
        onPress={(e) => {
          e.stopPropagation();
          onInvitePress(contact);
        }}
      >
        <Icon name="gift" size={16} color="#fff" style={{ marginRight: 6 }} />
        <Text style={styles.inviteButtonText}>Enviar & Invitar</Text>
      </TouchableOpacity>
    )}
  </TouchableOpacity>
), (prevProps, nextProps) => {
  // Custom comparison to prevent unnecessary re-renders
  return prevProps.contact.id === nextProps.contact.id &&
         prevProps.isOnConfio === nextProps.isOnConfio;
});

// Create isolated SearchInput component to prevent keyboard issues
const SearchInput = React.memo(({ 
  onSearchChange,
  isBusinessAccount 
}: { 
  onSearchChange: (text: string) => void;
  isBusinessAccount: boolean;
}) => {
  const [localValue, setLocalValue] = useState('');
  const debounceTimer = useRef<NodeJS.Timeout | null>(null);
  
  // Update local state when typing
  const handleLocalChange = useCallback((text: string) => {
    setLocalValue(text);
    
    // Debounce the parent update
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }
    
    debounceTimer.current = setTimeout(() => {
      onSearchChange(text);
    }, 300); // 300ms debounce
  }, [onSearchChange]);
  
  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, []);
  
  return (
    <TextInput 
      style={styles.searchInput}
      placeholder={isBusinessAccount ? "Buscar empleados..." : "Buscar contactos..."} 
      placeholderTextColor="#6b7280"
      value={localValue}
      onChangeText={handleLocalChange}
      autoCorrect={false}
      autoCapitalize="none"
      returnKeyType="search"
      blurOnSubmit={false}
    />
  );
});

export const ContactsScreen = () => {
  const navigation = useNavigation<ContactsScreenNavigationProp>();
  const apolloClient = useApolloClient();
  const [searchTerm, setSearchTerm] = useState('');
  
  // Test users mutation
  const [createTestUsers] = useMutation(CREATE_TEST_USERS);
  
  // Import useAccount to check account type
  const { activeAccount, user } = useAccount();
  
  // Check if this is a business account or confirmed personal account
  const isBusinessAccount = activeAccount?.type === 'business';
  const isPersonalAccount = activeAccount?.type === 'personal';
  
  // Debug logging for business account
  React.useEffect(() => {
    if (isBusinessAccount) {
      console.log('ContactsScreen - Business account debug:', {
        isBusinessAccount,
        activeAccountId: activeAccount?.id,
        activeAccountType: activeAccount?.type,
        businessName: activeAccount?.business?.name,
        businessId: activeAccount?.business?.id,
        isEmployee: activeAccount?.isEmployee,
        employeeRole: activeAccount?.employeeRole
      });
      
      // Log query status
      console.log('ContactsScreen - Query status:', {
        employeesLoading,
        employeesError: employeesError?.message,
        employeesData: employeesData?.currentBusinessEmployees?.length || 0,
        invitationsLoading,
        invitationsError: invitationsError?.message,
        invitationsData: invitationsData?.currentBusinessInvitations?.length || 0,
        skip: !isBusinessAccount,
      });
    }
  }, [isBusinessAccount, activeAccount, employeesLoading, employeesError, employeesData, invitationsLoading, invitationsError, invitationsData]);
  
  // Fetch employees and invitations for business accounts using JWT context
  const { data: employeesData, loading: employeesLoading, error: employeesError, refetch: refetchEmployees } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    onError: (error) => {
      console.error('Error fetching current business employees:', error);
    }
  });
  
  const { data: invitationsData, loading: invitationsLoading, error: invitationsError, refetch: refetchInvitations } = useQuery(GET_CURRENT_BUSINESS_INVITATIONS, {
    variables: { status: 'pending' },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    onError: (error) => {
      console.error('Error fetching current business invitations:', error);
    }
  });
  
  const [inviteEmployee] = useMutation(INVITE_EMPLOYEE);
  const [cancelInvitation] = useMutation(CANCEL_INVITATION);
  
  // Stable callback for search updates
  const handleSearchChange = useCallback((text: string) => {
    setSearchTerm(text);
  }, []);
  const [showTokenSelection, setShowTokenSelection] = useState(false);
  const [showSendTokenSelection, setShowSendTokenSelection] = useState(false);
  const [showFriendTokenSelection, setShowFriendTokenSelection] = useState(false);
  const [selectedFriend, setSelectedFriend] = useState<any>(null);
  const [showPermissionModal, setShowPermissionModal] = useState(false);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [isLoadingContacts, setIsLoadingContacts] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [contactsFromDevice, setContactsFromDevice] = useState<any[]>([]);
  const [hasContactPermission, setHasContactPermission] = useState<boolean | null>(null);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  
  // Batch all contact state into a single object for performance
  const [contactsData, setContactsData] = useState<{
    friends: any[];
    nonConfioFriends: any[];
    allContacts: any[];
    isLoaded: boolean;
  }>({ friends: [], nonConfioFriends: [], allContacts: [], isLoaded: false });

  // Check contact permission on mount - only for confirmed personal accounts
  useEffect(() => {
    if (!isPersonalAccount) {
      console.log('[PERF] Not personal account - skipping contact permission check');
      return;
    }
    console.log('[PERF] ContactsScreen mounted');
    const startTime = Date.now();
    checkContactPermission().then(() => {
      console.log(`[PERF] checkContactPermission completed in ${Date.now() - startTime}ms`);
    });
  }, [isPersonalAccount]);

  // Monitor contact loading in background - only for personal accounts
  useEffect(() => {
    if (!isPersonalAccount || !isInitialLoad || !hasContactPermission || contactsData.isLoaded) {
      return;
    }
    
    console.log('[PERF] Starting contact loading monitor');
    let checkCount = 0;
    
    // Check for contacts every 100ms until loaded
    const checkInterval = setInterval(async () => {
      checkCount++;
      const checkStart = Date.now();
      const contacts = await contactService.getAllContacts();
      console.log(`[PERF] Check #${checkCount}: getAllContacts took ${Date.now() - checkStart}ms, got ${contacts.length} contacts`);
      
      if (contacts.length > 0) {
        const displayStart = Date.now();
        await displayContacts(contacts);
        console.log(`[PERF] displayContacts took ${Date.now() - displayStart}ms`);
        setIsInitialLoad(false);
        clearInterval(checkInterval);
      }
    }, 100);

    // Clear interval after 5 seconds to prevent infinite checking
    setTimeout(() => {
      clearInterval(checkInterval);
      setIsInitialLoad(false);
    }, 5000);

    return () => clearInterval(checkInterval);
  }, [hasContactPermission, isInitialLoad, contactsData.isLoaded, isPersonalAccount]);

  // Check and request contact permission
  const checkContactPermission = async () => {
    try {
      const hasPermission = await contactService.hasContactPermission();
      setHasContactPermission(hasPermission);
      
      if (hasPermission) {
        console.log('[PERF] Has permission, getting initial contacts');
        const getContactsStart = Date.now();
        
        // Get initial contacts (may be empty if still loading)
        const contacts = await contactService.getAllContacts();
        console.log(`[PERF] Initial getAllContacts took ${Date.now() - getContactsStart}ms, got ${contacts.length} contacts`);
        
        if (contacts.length > 0) {
          // Display immediately if available
          const displayStart = Date.now();
          await displayContacts(contacts);
          console.log(`[PERF] Initial displayContacts took ${Date.now() - displayStart}ms`);
          setIsInitialLoad(false);
        }
        
        // No automatic sync - users will use pull-to-refresh or sync button
      } else {
        // Check if user has previously denied
        const storedStatus = await contactService.getStoredPermissionStatus();
        if (!storedStatus || storedStatus === 'pending') {
          // Show permission modal if not previously denied
          setShowPermissionModal(true);
        }
      }
    } catch (error) {
      console.error('Error checking contact permission:', error);
    }
  };

  // No longer need the query here since contacts are checked during sync

  // Display contacts from cache or fresh sync - OPTIMIZED WITH SINGLE STATE UPDATE
  const displayContacts = async (allContacts: any[]) => {
    const startTime = Date.now();
    
    if (allContacts.length === 0) {
      console.log('No contacts to display');
      setContactsData({ friends: [], nonConfioFriends: [], allContacts: [], isLoaded: true });
      return;
    }
    
    console.log(`[PERF] Starting to format ${allContacts.length} contacts`);
    const formatStart = Date.now();
    
    // Format contacts using the cached Confío status
    const formattedContacts = allContacts.map((contact, index) => ({
      id: contact.isOnConfio && contact.confioUserId ? contact.confioUserId : `contact_${index}`,
      name: contact.name || 'Sin nombre',
      avatar: contact.name ? contact.name.charAt(0).toUpperCase() : '?',
      phone: contact.phoneNumbers && contact.phoneNumbers[0] ? contact.phoneNumbers[0] : '',
      isOnConfio: contact.isOnConfio || false,
      userId: contact.confioUserId || null,
      suiAddress: contact.confioSuiAddress || null
    }));
    
    console.log(`[PERF] Formatting took ${Date.now() - formatStart}ms`);
    
    // Split into Confío users and non-Confío users
    const splitStart = Date.now();
    const confioUsers = formattedContacts.filter(contact => contact.isOnConfio);
    const nonConfioUsers = formattedContacts.filter(contact => !contact.isOnConfio);
    
    console.log(`[PERF] Found ${confioUsers.length} Confío users and ${nonConfioUsers.length} non-Confío users`);
    console.log(`[PERF] Splitting contacts took ${Date.now() - splitStart}ms`);
    
    // SINGLE STATE UPDATE - This is the key optimization!
    const setStateStart = Date.now();
    setContactsData({
      friends: confioUsers,
      nonConfioFriends: nonConfioUsers,
      allContacts: allContacts,
      isLoaded: true
    });
    console.log(`[PERF] setState call took ${Date.now() - setStateStart}ms`);
    
    console.log(`[PERF] Total displayContacts time: ${Date.now() - startTime}ms`);
  };

  // Sync contacts with device
  const syncContacts = async () => {
    // Only for personal accounts
    if (!isPersonalAccount) {
      return;
    }
    
    setIsLoadingContacts(true);
    try {
      const success = await contactService.syncContacts(apolloClient);
      console.log('Sync success:', success);
      
      if (success) {
        // Get all contacts from device
        const allContacts = await contactService.getAllContacts();
        console.log('Retrieved contacts:', allContacts.length);
        
        await displayContacts(allContacts);
      }
    } catch (error) {
      console.error('Error syncing contacts:', error);
      // Show empty state with sync button if error occurs
    } finally {
      setIsLoadingContacts(false);
      setRefreshing(false);
    }
  };

  // Handle permission allow
  const handlePermissionAllow = async () => {
    setShowPermissionModal(false);
    const granted = await contactService.requestContactPermission();
    
    if (granted) {
      setHasContactPermission(true);
      await contactService.storePermissionStatus('granted');
      await syncContacts();
    } else {
      setHasContactPermission(false);
      await contactService.storePermissionStatus('denied');
      
      // On iOS, if permission is denied, we need to guide user to settings
      if (Platform.OS === 'ios') {
        setTimeout(() => {
          Alert.alert(
            'Permisos de Contactos',
            'Para usar esta función, ve a Configuración > Confío > Contactos y activa el acceso.',
            [
              { text: 'Cancelar', style: 'cancel' },
              { text: 'Abrir Configuración', onPress: () => Linking.openSettings() }
            ]
          );
        }, 500);
      }
    }
  };

  // Handle permission deny
  const handlePermissionDeny = async () => {
    setShowPermissionModal(false);
    setHasContactPermission(false);
    await contactService.storePermissionStatus('denied');
  };

  // Handle test user creation (DEBUG only)
  const handleCreateTestUsers = async () => {
    if (!__DEV__) {
      Alert.alert('Error', 'Esta función solo está disponible en modo desarrollo');
      return;
    }
    
    Alert.alert(
      'Crear Usuarios de Prueba',
      '¿Quieres crear usuarios de prueba para todos tus contactos que no están en Confío?',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Crear',
          onPress: async () => {
            try {
              // Get all non-Confío contacts
              const nonConfioPhones = contactsData.nonConfioFriends
                .map(contact => contact.phone)
                .filter(phone => phone && phone.trim() !== '');
              
              if (nonConfioPhones.length === 0) {
                Alert.alert('Sin contactos', 'No hay contactos que no estén en Confío');
                return;
              }
              
              console.log(`[TEST] Creating test users for ${nonConfioPhones.length} phone numbers:`, nonConfioPhones);
              
              const result = await createTestUsers({
                variables: { phoneNumbers: nonConfioPhones }
              });
              
              console.log('[TEST] Mutation result:', result);
              
              if (result.data?.createTestUsers?.success) {
                const createdCount = result.data.createTestUsers.createdCount;
                const errorMsg = result.data.createTestUsers.error;
                
                if (createdCount > 0) {
                  Alert.alert(
                    'Éxito',
                    errorMsg || `Se crearon ${createdCount} usuarios de prueba.\n\nAhora sincroniza los contactos para verlos.`,
                    [{ text: 'OK', onPress: () => handleRefresh() }]
                  );
                } else {
                  Alert.alert(
                    'Sin usuarios creados',
                    errorMsg || 'No se crearon usuarios nuevos. Es posible que todos los números ya existan en la base de datos.',
                    [{ text: 'OK' }]
                  );
                }
              } else {
                Alert.alert('Error', result.data?.createTestUsers?.error || 'Error al crear usuarios de prueba');
              }
            } catch (error) {
              console.error('Error creating test users:', error);
              Alert.alert('Error', 'No se pudieron crear los usuarios de prueba');
            }
          }
        }
      ]
    );
  };

  // Handle pull to refresh
  const handleRefresh = async () => {
    setRefreshing(true);
    
    if (isBusinessAccount) {
      // Refresh employees and invitations for business accounts
      try {
        await Promise.all([
          refetchEmployees(),
          refetchInvitations()
        ]);
      } catch (error) {
        console.error('Error refreshing business data:', error);
      } finally {
        setRefreshing(false);
      }
      return;
    }
    
    if (!isPersonalAccount) {
      setRefreshing(false);
      return;
    }
    
    setIsLoadingContacts(true);
    
    // Clear existing contacts to show loading state
    setContactsData({ friends: [], nonConfioFriends: [], allContacts: [], isLoaded: false });
    
    if (hasContactPermission) {
      // Manual refresh - always sync
      console.log('[SYNC] Manual refresh - syncing contacts');
      const success = await contactService.syncContacts(apolloClient);
      if (success) {
        const allContacts = await contactService.getAllContacts();
        await displayContacts(allContacts);
      }
    } else {
      // If no permission, try requesting again
      const granted = await contactService.requestContactPermission();
      if (granted) {
        setHasContactPermission(true);
        const success = await contactService.syncContacts(apolloClient);
        if (success) {
          const allContacts = await contactService.getAllContacts();
          await displayContacts(allContacts);
        }
      }
    }
    
    setRefreshing(false);
    setIsLoadingContacts(false);
  };

  // Use focus effect to refresh contacts when screen comes into focus
  useFocusEffect(
    useCallback(() => {
      // Don't auto-sync on focus, just use cached data
      // Users can manually refresh if needed
    }, [hasContactPermission])
  );

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
    // Include Sui address if available
    const friendWithAddress = {
      ...friend,
      suiAddress: friend.suiAddress || null
    };
    setSelectedFriend(friendWithAddress);
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

  // Filter friends based on search term - Memoized to prevent keyboard dismissal
  const filteredConfioFriends = useMemo(() => 
    contactsData.friends
      .filter(friend =>
        friend.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        friend.phone.includes(searchTerm)
      )
      .sort((a, b) => a.name.localeCompare(b.name)), 
    [contactsData.friends, searchTerm]
  );

  const filteredNonConfioFriends = useMemo(() =>
    contactsData.nonConfioFriends
      .filter(friend =>
        friend.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        friend.phone.includes(searchTerm)
      )
      .sort((a, b) => a.name.localeCompare(b.name)),
    [contactsData.nonConfioFriends, searchTerm]
  );

  const handleFriendPress = (contact: any) => {
    // Navigate all friends to FriendDetail, regardless of Confío status
    navigation.navigate('FriendDetail', {
      friendId: contact.userId || contact.id,
      friendName: contact.name,
      friendAvatar: contact.avatar,
      friendPhone: contact.phone,
      isOnConfio: contact.isOnConfio || false
    });
  };

  // Memoized callbacks to prevent recreation on every render
  const handleFriendPressCallback = useCallback((contact: any) => {
    handleFriendPress(contact);
  }, []);
  
  const handleSendToFriendCallback = useCallback((contact: any) => {
    handleSendToFriend(contact);
  }, []);
  
  const handleInviteFriendCallback = useCallback((contact: any) => {
    handleInviteFriend(contact);
  }, []);

  // Employee management handlers
  const handleEmployeePress = useCallback((contact: any) => {
    if (contact.isInvitation) {
      // Show invitation details
      Alert.alert(
        'Invitación Pendiente',
        `Invitación enviada a ${contact.name} (${contact.phone})\nRol: ${getRoleLabel(contact.role)}`,
        [
          { text: 'Cancelar Invitación', onPress: () => handleCancelInvitation(contact), style: 'destructive' },
          { text: 'Cerrar', style: 'cancel' }
        ]
      );
    } else {
      // Navigate directly to employee detail screen
      navigation.navigate('EmployeeDetail', {
        employeeId: contact.id,
        employeeName: contact.name,
        employeePhone: contact.phone,
        employeeRole: contact.role,
        isActive: contact.isActive,
        employeeData: contact.employeeData || contact.employee
      });
    }
  }, [navigation]);

  // Handle employee actions menu (three dots button)
  const handleEmployeeActions = useCallback((contact: any) => {
    Alert.alert(
      'Acciones del Empleado',
      `${contact.name}\nRol: ${getRoleLabel(contact.role)}\nEstado: ${contact.isActive ? 'Activo' : 'Inactivo'}`,
      [
        { text: contact.isActive ? 'Desactivar' : 'Activar', onPress: () => handleToggleEmployee(contact) },
        { text: 'Remover', onPress: () => handleRemoveEmployee(contact), style: 'destructive' },
        { text: 'Cancelar', style: 'cancel' }
      ]
    );
  }, []);

  const handleToggleEmployee = useCallback(async (contact: any) => {
    // TODO: Implement employee activation/deactivation
    console.log('Toggle employee:', contact);
    Alert.alert('Funcionalidad Pendiente', 'La activación/desactivación de empleados estará disponible pronto.');
  }, []);

  const handleRemoveEmployee = useCallback(async (contact: any) => {
    Alert.alert(
      'Confirmar Eliminación',
      `¿Estás seguro de que quieres remover a ${contact.name} como empleado?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { 
          text: 'Remover', 
          style: 'destructive',
          onPress: async () => {
            // TODO: Implement employee removal
            console.log('Remove employee:', contact);
            Alert.alert('Funcionalidad Pendiente', 'La eliminación de empleados estará disponible pronto.');
          }
        }
      ]
    );
  }, []);

  const handleCancelInvitation = useCallback(async (contact: any) => {
    try {
      const result = await cancelInvitation({
        variables: { invitationId: contact.invitationData.id }
      });

      if (result.data?.cancelInvitation?.success) {
        Alert.alert('Éxito', 'Invitación cancelada correctamente.');
        // Refresh invitations
        refetchInvitations();
      } else {
        Alert.alert('Error', result.data?.cancelInvitation?.errors?.[0] || 'Error al cancelar la invitación');
      }
    } catch (error) {
      console.error('Error canceling invitation:', error);
      Alert.alert('Error', 'No se pudo cancelar la invitación. Intenta de nuevo.');
    }
  }, [cancelInvitation, refetchInvitations]);

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
            <Text style={styles.modalTitle}>Selecciona la moneda</Text>
            <TouchableOpacity onPress={() => setShowTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          
          <Text style={styles.modalSubtitle}>
            ¿Qué moneda quieres recibir?
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
                  <Text style={styles.tokenName}>Confío</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>
                    Moneda de gobernanza y utilidad
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
            <Text style={styles.modalTitle}>Selecciona la moneda</Text>
            <TouchableOpacity onPress={() => setShowSendTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.modalSubtitle}>¿Qué moneda quieres enviar?</Text>
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
                  <Text style={styles.tokenName}>Confío</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>Moneda de gobernanza y utilidad</Text>
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
            <Text style={styles.modalTitle}>Selecciona la moneda</Text>
            <TouchableOpacity onPress={() => setShowFriendTokenSelection(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <Text style={styles.modalSubtitle}>¿Qué moneda quieres enviar a {selectedFriend?.name}?</Text>
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
                  <Text style={styles.tokenName}>Confío</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>Moneda de gobernanza y utilidad</Text>
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

  // Prepare sections for SectionList
  const sections = useMemo(() => {
    // For business accounts, show employees section (but not for employees themselves)
    if (isBusinessAccount && !activeAccount?.isEmployee) {
      // Show loading state
      if (employeesLoading || invitationsLoading) {
        return [{
          title: 'EMPLEADOS',
          count: 0,
          data: [],
          isEmployees: true,
          isLoading: true
        }];
      }
      const employees = employeesData?.currentBusinessEmployees || [];
      const invitations = invitationsData?.currentBusinessInvitations || [];
      
      // Format employees for display - exclude the business owner
      const employeeContacts = employees
        .filter(employee => {
          // Filter out the business owner (current user)
          const currentUserId = user?.id;
          return employee.user.id !== currentUserId;
        })
        .map(employee => ({
          id: `employee-${employee.id}`,
          name: `${employee.user.firstName || ''} ${employee.user.lastName || ''}`.trim() || employee.user.username,
          phone: formatPhoneNumber(employee.user.phoneNumber, employee.user.phoneCountry),
          avatar: (employee.user.firstName?.[0] || employee.user.username?.[0] || 'E').toUpperCase(),
          role: employee.role,
          isActive: employee.isActive,
          permissions: employee.effectivePermissions,
          isEmployee: true,
          employeeData: employee
        }));
      
      // Format pending invitations
      const invitationContacts = invitations.map(invitation => ({
        id: `invitation-${invitation.id}`,
        name: invitation.employeeName || 'Invitación pendiente',
        phone: formatPhoneNumber(invitation.employeePhone, invitation.employeePhoneCountry),
        avatar: '?',
        role: invitation.role,
        isInvitation: true,
        invitationData: invitation
      }));
      
      // Filter by search term
      const filteredEmployees = searchTerm
        ? employeeContacts.filter(contact =>
            contact.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            contact.phone.includes(searchTerm)
          )
        : employeeContacts;
      
      const filteredInvitations = searchTerm
        ? invitationContacts.filter(contact =>
            contact.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            contact.phone.includes(searchTerm)
          )
        : invitationContacts;
      
      const sections = [];
      
      if (filteredEmployees.length > 0 || filteredInvitations.length > 0) {
        sections.push({
          title: 'EMPLEADOS',
          count: filteredEmployees.length + filteredInvitations.length,
          data: [...filteredEmployees, ...filteredInvitations],
          isEmployees: true
        });
      }
      
      return sections;
    }
    
    const sectionData = [];
    
    if (filteredConfioFriends.length > 0) {
      sectionData.push({
        title: 'Amigos en Confío',
        count: filteredConfioFriends.length,
        data: filteredConfioFriends,
        isConfio: true
      });
    }
    
    if (filteredNonConfioFriends.length > 0) {
      sectionData.push({
        title: 'Invita a tus amigos',
        count: filteredNonConfioFriends.length,
        data: filteredNonConfioFriends,
        isConfio: false,
        showInfo: true
      });
    }
    
    return sectionData;
  }, [filteredConfioFriends, filteredNonConfioFriends, isBusinessAccount, activeAccount, employeesLoading, invitationsLoading, employeesData, invitationsData, searchTerm]);

  const renderSectionHeader = useCallback(({ section }) => (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Text style={[styles.sectionTitle, section.isEmployees && styles.employeeSectionTitle]}>{section.title}</Text>
        <View style={styles.sectionHeaderRight}>
          {section.isLoading ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <View style={styles.sectionCount}>
              <Text style={styles.sectionCountText}>{section.count}</Text>
            </View>
          )}
          {section.isEmployees && !section.isLoading && (
            <TouchableOpacity 
              style={styles.addEmployeeHeaderButton}
              onPress={() => setShowInviteModal(true)}
            >
              <Icon name="user-plus" size={16} color={colors.primary} />
            </TouchableOpacity>
          )}
        </View>
      </View>
      
      {section.showInfo && (
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
      )}
      
      {section.isEmployees && section.count === 0 && !activeAccount?.isEmployee && (
        <View style={styles.employeeInfoCard}>
          <View style={styles.infoCardContent}>
            <View style={[styles.infoIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="user-plus" size={16} color="#fff" />
            </View>
            <View style={styles.infoTextContainer}>
              <Text style={styles.infoTitle}>Añade tu primer empleado</Text>
              <Text style={styles.infoDescription}>
                Los empleados pueden recibir pagos en nombre de tu negocio. Solo tú, como propietario, tienes control para enviar dinero.
              </Text>
            </View>
          </View>
          
          <TouchableOpacity 
            style={styles.addEmployeeFromInfoButton}
            onPress={() => {
              setShowInviteModal(true);
            }}
          >
            <Icon name="user-plus" size={16} color="#fff" style={{ marginRight: 8 }} />
            <Text style={styles.addEmployeeFromInfoButtonText}>Añadir empleado</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  ), []);

  const renderItem = useCallback(({ item, section }) => {
    // For business accounts showing employees
    if (section.isEmployees) {
      return (
        <EmployeeCard 
          contact={item} 
          onPress={handleEmployeePress}
          onRemove={handleEmployeeActions}
          onCancelInvitation={handleCancelInvitation}
        />
      );
    }
    
    // For regular contacts
    return (
      <ContactCard 
        contact={item} 
        isOnConfio={item.isOnConfio || false}
        onPress={handleFriendPressCallback}
        onSendPress={handleSendToFriendCallback}
        onInvitePress={handleInviteFriendCallback}
      />
    );
  }, [handleFriendPressCallback, handleSendToFriendCallback, handleInviteFriendCallback, handleEmployeePress, handleEmployeeActions, handleCancelInvitation]);

  // Create a stable header component that won't cause re-renders
  const ListHeaderComponent = useMemo(() => {
    const HeaderContent = () => (
      <>

      {/* Send/Receive Options */}
      <View style={styles.actionSection}>
        {/* For business accounts, show the Add Employee button */}
        {isBusinessAccount && (
          <TouchableOpacity 
            style={styles.addEmployeeActionButton}
            onPress={() => {
              setShowInviteModal(true);
            }}
          >
            <View style={styles.actionButtonContent}>
              <View style={[styles.actionIconContainer, { backgroundColor: colors.violet }]}>
                <Icon name="user-plus" size={20} color="#fff" />
              </View>
              <View style={styles.actionTextContainer}>
                <Text style={styles.actionButtonTitle}>Añadir empleado</Text>
                <Text style={styles.actionButtonSubtitle}>Gestiona tu equipo de trabajo</Text>
              </View>
            </View>
            <Icon name="chevron-right" size={20} color="#9ca3af" />
          </TouchableOpacity>
        )}
        
        {/* Show permission prompt if user denied but there are no contacts - only for personal accounts */}
        {isPersonalAccount && hasContactPermission === false && contactsData.friends.length === 0 && contactsData.nonConfioFriends.length === 0 && (
          <TouchableOpacity 
            style={styles.permissionPrompt}
            onPress={async () => {
              const status = await contactService.getStoredPermissionStatus();
              if (status === 'denied' && Platform.OS === 'ios') {
                Alert.alert(
                  'Permisos de Contactos',
                  'Para ver los nombres de tus amigos, ve a Configuración > Confío > Contactos y activa el acceso.',
                  [
                    { text: 'Cancelar', style: 'cancel' },
                    { text: 'Abrir Configuración', onPress: () => Linking.openSettings() }
                  ]
                );
              } else {
                setShowPermissionModal(true);
              }
            }}
          >
            <View style={styles.permissionPromptIcon}>
              <Icon name="shield" size={20} color={colors.primary} />
            </View>
            <View style={styles.permissionPromptContent}>
              <Text style={styles.permissionPromptTitle}>Activar contactos</Text>
              <Text style={styles.permissionPromptText}>
                Permite el acceso para ver los nombres de tus amigos
              </Text>
            </View>
            <Icon name="chevron-right" size={20} color="#9ca3af" />
          </TouchableOpacity>
        )}
        
        {activeAccount?.isEmployee ? (
          // Employee welcome message
          <View style={styles.employeeWelcomeContainer}>
            <View style={styles.employeeWelcomeIcon}>
              <Icon name="users" size={40} color="#7c3aed" />
            </View>
            <Text style={styles.employeeWelcomeTitle}>
              Equipo {activeAccount?.business?.name}
            </Text>
            <Text style={styles.employeeWelcomeText}>
              ¡Bienvenido! Como {activeAccount?.employeeRole === 'cashier' ? 'cajero' : activeAccount?.employeeRole === 'manager' ? 'gerente' : activeAccount?.employeeRole === 'admin' ? 'administrador' : 'parte del equipo'}, eres fundamental para el éxito del negocio.
              {'\n\n'}
              {activeAccount?.employeePermissions?.acceptPayments ? 
                '💡 Consejo: Usa el botón "Cobrar" para recibir pagos de los clientes de forma rápida y segura.' : 
                'Tu rol está enfocado en otras áreas importantes del negocio.'}
            </Text>
          </View>
        ) : (
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
        )}
      </View>
    </>
    );
    
    return HeaderContent;
  }, [searchTerm, hasContactPermission, isLoadingContacts, refreshing, contactsData.friends.length, contactsData.nonConfioFriends.length, handleSendWithAddress, handleRefresh, isBusinessAccount, isPersonalAccount]);

  const ListEmptyComponent = useCallback(() => {
    // For business accounts
    if (isBusinessAccount) {
      // Check if there was an error loading employees  
      if ((employeesError || invitationsError) && !activeAccount?.isEmployee) {
        console.error('ContactsScreen - Error details:', {
          employeesError: employeesError?.message,
          invitationsError: invitationsError?.message,
          networkError: employeesError?.networkError,
          graphQLErrors: employeesError?.graphQLErrors
        });
        
        return (
          <View style={styles.emptyState}>
            <View style={styles.emptyIconContainer}>
              <Icon name="alert-circle" size={32} color="#ef4444" />
            </View>
            <Text style={styles.emptyTitle}>Error al cargar empleados</Text>
            <Text style={styles.emptyDescription}>
              No se pudieron cargar los empleados. Por favor, intenta de nuevo.
              {employeesError?.message && `\n\nError: ${employeesError.message}`}
            </Text>
            <TouchableOpacity 
              style={styles.retryButton}
              onPress={() => {
                refetchEmployees();
                refetchInvitations();
              }}
            >
              <Icon name="refresh-cw" size={20} color="#fff" style={{ marginRight: 8 }} />
              <Text style={styles.retryButtonText}>Reintentar</Text>
            </TouchableOpacity>
          </View>
        );
      }
      
      // Check if user is an employee - just return null to hide the section
      if (activeAccount?.isEmployee) {
        return null;
      }
      
      // Business owner view
      return (
        <View style={styles.emptyState}>
          <View style={styles.emptyIconContainer}>
            <Icon name="users" size={32} color="#9ca3af" />
          </View>
          <Text style={styles.emptyTitle}>Añade tu primer empleado</Text>
          <Text style={styles.emptyDescription}>
            Los empleados pueden recibir pagos en nombre de tu negocio. Solo tú, como propietario, tienes control para enviar dinero.
          </Text>
          
          <TouchableOpacity 
            style={styles.addEmployeeButton}
            onPress={() => {
              setShowInviteModal(true);
            }}
          >
            <Icon name="user-plus" size={20} color="#fff" style={{ marginRight: 8 }} />
            <Text style={styles.addEmployeeButtonText}>Añadir empleado</Text>
          </TouchableOpacity>
        </View>
      );
    }
    
    if (searchTerm) {
      return (
        <View style={styles.emptyState}>
          <View style={styles.emptyIconContainer}>
            <Icon name="users" size={32} color="#9ca3af" />
          </View>
          <Text style={styles.emptyTitle}>No se encontraron contactos</Text>
          <Text style={styles.emptyDescription}>
            No hay contactos que coincidan con "{searchTerm}"
          </Text>
        </View>
      );
    }
    
    if (!isInitialLoad && !isLoadingContacts) {
      return (
        <View style={styles.emptyState}>
          <View style={styles.emptyIconContainer}>
            <Icon name="users" size={32} color="#9ca3af" />
          </View>
          <Text style={styles.emptyTitle}>
            {hasContactPermission === false ? 'Acceso a contactos denegado' : 'No hay contactos'}
          </Text>
          <Text style={styles.emptyDescription}>
            {hasContactPermission === false 
              ? 'Permite el acceso a tus contactos para enviar dinero fácilmente a tus amigos' 
              : 'Sincroniza tus contactos para empezar a enviar dinero'}
          </Text>
          
          <View style={styles.emptyButtonsContainer}>
            {hasContactPermission === false ? (
              <TouchableOpacity 
                style={styles.permissionButton}
                onPress={async () => {
                  // Check if permission was previously denied
                  const status = await contactService.getStoredPermissionStatus();
                  if (status === 'denied' && Platform.OS === 'ios') {
                    // On iOS, guide to settings
                    Alert.alert(
                      'Permisos de Contactos',
                      'Para usar los contactos, ve a Configuración > Confío > Contactos y activa el acceso.',
                      [
                        { text: 'Cancelar', style: 'cancel' },
                        { text: 'Abrir Configuración', onPress: () => Linking.openSettings() }
                      ]
                    );
                  } else {
                    // First time or Android, show modal
                    setShowPermissionModal(true);
                  }
                }}
              >
                <Icon name="shield" size={20} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.permissionButtonText}>Permitir acceso a contactos</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity 
                style={styles.permissionButton}
                onPress={handleRefresh}
              >
                <Icon name="refresh-cw" size={20} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.permissionButtonText}>Sincronizar contactos</Text>
              </TouchableOpacity>
            )}
            
            {/* Button to guide to settings on iOS or show modal on Android */}
            {hasContactPermission === false && (
              <TouchableOpacity 
                style={styles.secondaryButton}
                onPress={async () => {
                  const status = await contactService.getStoredPermissionStatus();
                  if (status === 'denied' && Platform.OS === 'ios') {
                    Linking.openSettings();
                  } else {
                    setShowPermissionModal(true);
                  }
                }}
              >
                <Text style={styles.secondaryButtonText}>
                  {Platform.OS === 'ios' ? 'Abrir Configuración' : 'Ver información de privacidad'}
                </Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      );
    }
    
    return null;
  }, [searchTerm, isInitialLoad, isLoadingContacts, hasContactPermission, handleRefresh, isBusinessAccount, isPersonalAccount, activeAccount, employeesError, invitationsError, refetchEmployees, refetchInvitations]);

  return (
    <>
      <View style={styles.container}>
        {/* Move search bar outside of SectionList to prevent keyboard issues */}
        <View style={styles.searchSection}>
            <View style={styles.searchBarContainer}>
              <View style={styles.searchBar}>
                <Icon name="search" size={20} color="#9ca3af" style={styles.searchIcon} />
                <SearchInput 
                  onSearchChange={handleSearchChange}
                  isBusinessAccount={isBusinessAccount}
                />
              </View>
              
              {/* Manual sync button - always visible */}
              <TouchableOpacity 
                style={styles.syncButton}
                onPress={async () => {
                  if (isBusinessAccount) {
                    // For business accounts, refresh employees
                    handleRefresh();
                    return;
                  }
                  
                  if (!isPersonalAccount) {
                    return;
                  }
                  
                  if (hasContactPermission) {
                    handleRefresh(); // This will sync contacts
                  } else {
                    // Check if permission was previously denied
                    const status = await contactService.getStoredPermissionStatus();
                    if (status === 'denied' && Platform.OS === 'ios') {
                      // On iOS, guide to settings
                      Alert.alert(
                        'Permisos de Contactos',
                        'Para sincronizar contactos, ve a Configuración > Confío > Contactos y activa el acceso.',
                        [
                          { text: 'Cancelar', style: 'cancel' },
                          { text: 'Abrir Configuración', onPress: () => Linking.openSettings() }
                        ]
                      );
                    } else {
                      // First time or Android, show modal
                      setShowPermissionModal(true);
                    }
                  }
                }}
                disabled={isLoadingContacts || refreshing}
              >
                <Icon 
                  name={isBusinessAccount || hasContactPermission ? "refresh-cw" : "shield"} 
                  size={20} 
                  color={isLoadingContacts || refreshing ? "#9ca3af" : colors.primary} 
                />
              </TouchableOpacity>
            </View>
            
            {/* Test button - only in development and for personal accounts */}
            {__DEV__ && isPersonalAccount && contactsData.nonConfioFriends.length > 0 && (
              <TouchableOpacity 
                style={styles.testButton}
                onPress={handleCreateTestUsers}
              >
                <Icon name="user-plus" size={16} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.testButtonText}>
                  Crear {contactsData.nonConfioFriends.length} usuarios de prueba
                </Text>
              </TouchableOpacity>
            )}
          </View>
        
        <SectionList
          sections={sections}
          renderItem={renderItem}
          renderSectionHeader={renderSectionHeader}
          ListHeaderComponent={ListHeaderComponent}
          ListEmptyComponent={ListEmptyComponent}
          keyExtractor={(item, index) => item.id || `contact-${index}`}
          getItemLayout={(data, index) => (
            {length: 80, offset: 80 * index, index}
          )}
          removeClippedSubviews={true}
          maxToRenderPerBatch={10}
          windowSize={10}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ paddingBottom: 24 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={colors.primary}
            />
          }
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          removeClippedSubviews={true}
        />
        
        <TokenSelectionModal />
        <SendTokenSelectionModal />
        <FriendTokenSelectionModal />
      </View>

      {/* Beautiful Contact Permission Modal */}
      <ContactPermissionModal
        visible={showPermissionModal}
        onAllow={handlePermissionAllow}
        onDeny={handlePermissionDeny}
        onClose={() => setShowPermissionModal(false)}
      />
      
      {/* Employee Invitation Modal */}
      {isBusinessAccount && (
        <InviteEmployeeModal
          visible={showInviteModal}
          onClose={() => setShowInviteModal(false)}
          onSuccess={() => {
            setShowInviteModal(false);
            // Refresh both employees and invitations data
            refetchEmployees();
            refetchInvitations();
            console.log('Employee invitation successful, data refreshed');
          }}
        />
      )}
      
      {/* Loading overlay - only show for manual refresh and for personal accounts */}
      {isPersonalAccount && (isLoadingContacts || (isInitialLoad && hasContactPermission && !contactsData.isLoaded)) && (
        <View style={styles.loadingOverlay}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>
            {isInitialLoad ? 'Cargando contactos...' : 'Sincronizando contactos...'}
          </Text>
        </View>
      )}
    </>
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
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  searchBarContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  searchBar: {
    flex: 1,
    backgroundColor: '#f9fafb',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 16,
  },
  syncButton: {
    backgroundColor: '#f9fafb',
    padding: 12,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  testButton: {
    backgroundColor: '#8b5cf6',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 12,
    marginTop: 12,
  },
  testButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
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
  employeeWelcomeContainer: {
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
  },
  employeeWelcomeIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#ede9fe',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  employeeWelcomeTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#1f2937',
    textAlign: 'center',
    marginBottom: 8,
  },
  employeeWelcomeText: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 20,
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
  sectionHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  addEmployeeHeaderButton: {
    padding: 4,
    borderRadius: 8,
    backgroundColor: colors.primaryLight,
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
    paddingHorizontal: 20,
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
  employeeRole: {
    fontSize: 12,
    color: '#059669',
    marginTop: 2,
  },
  employeeActionContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
  },
  cancelButton: {
    padding: 8,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fef2f2',
    minWidth: 36,
    minHeight: 36,
  },
  moreButton: {
    padding: 8,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f9fafb',
    minWidth: 36,
    minHeight: 36,
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
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 999,
  },
  loadingText: {
    marginTop: 12,
    fontSize: 16,
    color: '#6B7280',
  },
  permissionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 999,
    marginTop: 24,
  },
  permissionButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  emptyButtonsContainer: {
    alignItems: 'center',
    marginTop: 16,
  },
  secondaryButton: {
    marginTop: 12,
    paddingVertical: 8,
  },
  secondaryButtonText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '500',
    textDecorationLine: 'underline',
  },
  permissionPrompt: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primaryLight,
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  permissionPromptIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  permissionPromptContent: {
    flex: 1,
  },
  permissionPromptTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.primaryDark,
    marginBottom: 2,
  },
  permissionPromptText: {
    fontSize: 13,
    color: colors.primaryDark,
    opacity: 0.8,
  },
  addEmployeeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 999,
    marginTop: 24,
  },
  addEmployeeButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  retryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ef4444',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 999,
    marginTop: 24,
  },
  retryButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  employeeSectionTitle: {
    // Same style as sectionTitle but could be customized if needed
  },
  addEmployeeActionButton: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    paddingVertical: 16,
    paddingHorizontal: 16,
    marginBottom: 8,
  },
  employeeInfoCard: {
    backgroundColor: colors.primaryLight,
    borderColor: colors.primary,
    borderWidth: 1,
    padding: 16,
    borderRadius: 16,
    marginBottom: 12,
  },
  addEmployeeFromInfoButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 12,
    marginTop: 12,
    alignSelf: 'flex-start',
  },
  addEmployeeFromInfoButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 14,
  },
});