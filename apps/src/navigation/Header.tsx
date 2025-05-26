import React from 'react';
import { View, Text, TouchableOpacity, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

export const HEADER_HEIGHT = Platform.OS === 'ios' ? 88 : 64;

interface HeaderProps {
  onProfilePress: () => void;
  onNotificationPress: () => void;
  isHomeScreen?: boolean;
  title?: string;
}

export function Header({
  onProfilePress,
  onNotificationPress,
  isHomeScreen = false,
  title = 'Confío',
}: HeaderProps) {
  return (
    <View
      style={{
        backgroundColor: isHomeScreen ? '#34d399' : '#F3F4F6',
        paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
        paddingBottom: 8,
        paddingHorizontal: 20,
        minHeight: HEADER_HEIGHT,
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <Text style={{ 
        fontSize: 24, 
        fontWeight: 'bold', 
        color: isHomeScreen ? '#fff' : '#1F2937' 
      }}>
        {title}
      </Text>
      {isHomeScreen && (
        <View style={{ flexDirection: 'row', gap: 12 }}>
          <TouchableOpacity 
            style={{ 
              padding: 8, 
              backgroundColor: 'rgba(255,255,255,0.2)', 
              borderRadius: 20 
            }} 
            onPress={onNotificationPress}
          >
            <Icon name="bell" size={20} color="#fff" />
          </TouchableOpacity>
          <TouchableOpacity 
            style={{ 
              padding: 8, 
              backgroundColor: '#fff', 
              borderRadius: 20 
            }} 
            onPress={onProfilePress}
          >
            <Icon name="user" size={20} color="#34d399" />
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
} 