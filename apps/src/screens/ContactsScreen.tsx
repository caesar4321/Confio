import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView, Platform } from 'react-native';
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
    <ScrollView style={styles.container} contentContainerStyle={styles.contentContainer} keyboardShouldPersistTaps="handled">
      {/* Search Bar */}
      <View style={styles.searchBar}>
        <Icon name="search" size={18} color="#6B7280" style={styles.searchIcon} />
        <TextInput
          style={styles.searchInput}
          placeholder="Buscar contactos..."
          placeholderTextColor="#6B7280"
        />
      </View>

      {/* Send/Receive Buttons */}
      <View style={styles.actionButtons}>
        <TouchableOpacity style={styles.actionButton}>
          <View style={styles.actionButtonContent}>
            <View style={styles.actionIconContainer}>
              <Icon name="send" size={20} color="#fff" />
            </View>
            <Text style={styles.actionButtonText}>Enviar con dirección</Text>
          </View>
          <Icon name="chevron-right" size={20} color="#6B7280" />
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <View style={styles.actionButtonContent}>
            <View style={styles.actionIconContainer}>
              <Icon name="download" size={20} color="#fff" />
            </View>
            <Text style={styles.actionButtonText}>Recibir con dirección</Text>
          </View>
          <Icon name="chevron-right" size={20} color="#6B7280" />
        </TouchableOpacity>
      </View>

      {/* Friends Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Amigos</Text>
        <View style={styles.friendsList}>
          {friends.map((friend, index) => (
            <View key={index} style={styles.friendItem}>
              <View style={styles.avatarContainer}>
                <Text style={styles.avatarText}>{friend.avatar}</Text>
              </View>
              <Text style={styles.friendName}>{friend.name}</Text>
              <TouchableOpacity style={styles.sendButton}>
                <Icon name="send" size={16} color="#fff" />
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
        <View style={styles.friendsList}>
          {nonConfioFriends.map((friend, index) => (
            <View key={index} style={styles.friendItem}>
              <View style={styles.avatarContainer}>
                <Text style={styles.avatarText}>{friend.avatar}</Text>
              </View>
              <Text style={styles.friendName}>{friend.name}</Text>
              <TouchableOpacity style={styles.addButton}>
                <Icon name="plus" size={16} color="#6B7280" />
              </TouchableOpacity>
            </View>
          ))}
        </View>
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  contentContainer: {
    paddingHorizontal: 16,
    paddingTop: 0,
    paddingBottom: 24,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: Platform.OS === 'ios' ? 12 : 8,
    marginBottom: 10,
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    fontSize: 15,
    color: '#1F2937',
    paddingVertical: 0,
  },
  actionButtons: {
    gap: 8,
    marginBottom: 16,
  },
  actionButton: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
    borderRadius: 16,
    paddingVertical: 16,
    paddingHorizontal: 16,
    marginBottom: 6,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.06,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  actionButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#34d399', // emerald-400
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 14,
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  section: {
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginBottom: 10,
  },
  friendsList: {
    gap: 8,
  },
  friendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 0,
  },
  avatarContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 14,
  },
  avatarText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#4B5563',
  },
  friendName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#34d399',
    justifyContent: 'center',
    alignItems: 'center',
  },
  addButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
  },
  inviteBanner: {
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    padding: 12,
    marginBottom: 14,
  },
  inviteText: {
    fontSize: 14,
    color: '#4B5563',
    textAlign: 'center',
  },
}); 