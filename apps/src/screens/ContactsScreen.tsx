import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

export const ContactsScreen = () => {
  // Mock data
  const friends = [
    { name: "Evelyn", isOnConfio: true, avatar: "E" },
    { name: "Julian", isOnConfio: true, avatar: "J" },
    { name: "Olivia", isOnConfio: true, avatar: "O" },
    { name: "Susy", isOnConfio: true, avatar: "S" }
  ];

  const nonConfioFriends = [
    { name: "Borris", avatar: "B" },
    { name: "Jeffrey", avatar: "J" },
    { name: "Juan", avatar: "J" },
    { name: "Yadira", avatar: "Y" }
  ];

  return (
    <View style={styles.container}>
      {/* Search Bar */}
      <View style={styles.searchContainer}>
        <Icon name="search" size={16} color="#6B7280" />
        <TextInput
          style={styles.searchInput}
          placeholder="Buscar contactos..."
          placeholderTextColor="#6B7280"
        />
      </View>

      {/* Send/Receive Bar */}
      <View style={styles.actionButtons}>
        <TouchableOpacity style={styles.actionButton}>
          <View style={styles.actionButtonContent}>
            <View style={styles.actionIconContainer}>
              <Icon name="send" size={20} color="#FFFFFF" />
            </View>
            <Text style={styles.actionButtonText}>Enviar con dirección</Text>
          </View>
          <Icon name="chevron-right" size={20} color="#6B7280" />
        </TouchableOpacity>

        <TouchableOpacity style={styles.actionButton}>
          <View style={styles.actionButtonContent}>
            <View style={styles.actionIconContainer}>
              <Icon name="download" size={20} color="#FFFFFF" />
            </View>
            <Text style={styles.actionButtonText}>Recibir con dirección</Text>
          </View>
          <Icon name="chevron-right" size={20} color="#6B7280" />
        </TouchableOpacity>
      </View>

      {/* Friends Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Amigos</Text>
        <View style={styles.contactsList}>
          {friends.map((friend, index) => (
            <View key={index} style={styles.contactItem}>
              <View style={styles.avatarContainer}>
                <Text style={styles.avatarText}>{friend.avatar}</Text>
              </View>
              <Text style={styles.contactName}>{friend.name}</Text>
              <TouchableOpacity style={styles.sendButton}>
                <Icon name="send" size={16} color="#FFFFFF" />
              </TouchableOpacity>
            </View>
          ))}
        </View>
      </View>

      {/* Non-Confío Friends */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Amigos que no están en Confío</Text>
        <View style={styles.inviteBanner}>
          <Text style={styles.inviteText}>¡Invita a tus amigos a Confío!</Text>
        </View>
        <View style={styles.contactsList}>
          {nonConfioFriends.map((friend, index) => (
            <View key={index} style={styles.contactItem}>
              <View style={styles.avatarContainer}>
                <Text style={styles.avatarText}>{friend.avatar}</Text>
              </View>
              <Text style={styles.contactName}>{friend.name}</Text>
              <TouchableOpacity style={styles.inviteButton}>
                <Icon name="plus" size={16} color="#6B7280" />
              </TouchableOpacity>
            </View>
          ))}
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 16,
  },
  header: {
    marginBottom: 24,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 24,
  },
  searchInput: {
    flex: 1,
    marginLeft: 8,
    fontSize: 14,
    color: '#1F2937',
  },
  actionButtons: {
    gap: 12,
    marginBottom: 24,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    padding: 16,
  },
  actionButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionIconContainer: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#72D9BC',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginBottom: 12,
  },
  contactsList: {
    gap: 12,
  },
  contactItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#4B5563',
  },
  contactName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  sendButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#72D9BC',
    justifyContent: 'center',
    alignItems: 'center',
  },
  inviteButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
  },
  inviteBanner: {
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  inviteText: {
    fontSize: 14,
    color: '#4B5563',
    textAlign: 'center',
  },
}); 