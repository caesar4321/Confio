import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';

// Colors from the design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

export const ProfileScreen = () => {
  const { signOut } = useAuth();

  const profileOptions = [
    { name: "Verificación", icon: "user-check" },
    { name: "Seguridad", icon: "shield" },
    { name: "Notificaciones", icon: "bell" },
    { name: "Comunidad", icon: "users" },
    { name: "Términos de Servicio", icon: "file-text" },
    { name: "Política de Privacidad", icon: "lock" },
    { name: "Eliminación de Datos", icon: "trash-2" }
  ];

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
      {/* Header Section */}
      <View style={styles.header}>
        <View style={styles.profileInfo}>
          <View style={styles.avatarContainer}>
            <Icon name="user" size={40} color={colors.primary} />
          </View>
          <Text style={styles.name}>Carlos Mendoza</Text>
          <Text style={styles.phone}>+58 412 345 6789</Text>
        </View>
      </View>

      {/* Confío Address Card */}
      <View style={styles.addressCard}>
        <View style={styles.addressCardContent}>
          <View style={styles.addressIconContainer}>
            <Icon name="maximize" size={20} color="#6B7280" />
          </View>
          <View style={styles.addressInfo}>
            <Text style={styles.addressTitle}>Mi dirección de Confío</Text>
            <Text style={styles.addressValue}>confio.lat/carlosmendoza</Text>
          </View>
          <TouchableOpacity style={styles.shareButton}>
            <Text style={styles.shareButtonText}>Compartir</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Profile Options */}
      <View style={styles.optionsContainer}>
        {profileOptions.map((option, index) => (
          <TouchableOpacity key={index} style={styles.optionItem}>
            <View style={styles.optionLeft}>
              <View style={styles.optionIconContainer}>
                <Icon name={option.icon} size={20} color="#6B7280" />
              </View>
              <Text style={styles.optionText}>{option.name}</Text>
            </View>
            <Icon name="chevron-right" size={20} color="#9CA3AF" />
          </TouchableOpacity>
        ))}
      </View>

      {/* Sign Out Button */}
      <TouchableOpacity style={styles.signOutButton} onPress={signOut}>
        <Text style={styles.signOutText}>Cerrar Sesión</Text>
      </TouchableOpacity>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    backgroundColor: '#34d399', // emerald-400
    paddingBottom: 32,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  profileInfo: {
    alignItems: 'center',
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#fff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
  },
  name: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 4,
  },
  phone: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  addressCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    marginTop: -16,
    marginHorizontal: 16,
    marginBottom: 24,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  addressCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
  },
  addressIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  addressInfo: {
    flex: 1,
  },
  addressTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginBottom: 2,
  },
  addressValue: {
    fontSize: 12,
    color: '#6B7280',
  },
  shareButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  shareButtonText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '500',
  },
  optionsContainer: {
    paddingHorizontal: 16,
    gap: 12,
  },
  optionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.neutralDark,
    padding: 12,
    borderRadius: 12,
  },
  optionLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  optionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#fff',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  optionText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  signOutButton: {
    marginTop: 32,
    marginBottom: 32,
    paddingVertical: 12,
    alignItems: 'center',
  },
  signOutText: {
    color: '#EF4444',
    fontSize: 16,
    fontWeight: '500',
  },
}); 