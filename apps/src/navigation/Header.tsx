import React from 'react';
import { View, Text, TouchableOpacity, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { NavigationProp } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

export const HEADER_HEIGHT = Platform.OS === 'ios' ? 88 : 64;

interface HeaderProps {
  title: string;
  navigation: NavigationProp<RootStackParamList>;
  isHomeScreen?: boolean;
  onProfilePress?: () => void;
  onNotificationPress?: () => void;
  backgroundColor?: string;
  isLight?: boolean;
  showBackButton?: boolean;
  unreadNotifications?: number;
  currentAccountAvatar?: string;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  navigation,
  isHomeScreen = false,
  onProfilePress,
  onNotificationPress,
  backgroundColor,
  isLight = false,
  showBackButton = true,
  unreadNotifications = 0,
  currentAccountAvatar = 'U',
}) => {
  const isLightTheme = isLight || isHomeScreen;
  const textColor = isLightTheme ? '#FFFFFF' : '#1F2937';
  
  return (
    <View
      style={{
        backgroundColor: backgroundColor ? backgroundColor : (isHomeScreen ? '#34d399' : '#F3F4F6'),
        paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
        paddingBottom: 8,
        paddingHorizontal: 20,
        minHeight: HEADER_HEIGHT,
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        {showBackButton && !isHomeScreen && (
          <TouchableOpacity 
            onPress={() => navigation.goBack()}
            style={{ marginRight: 16 }}
          >
            <Icon name="arrow-left" size={24} color={textColor} />
          </TouchableOpacity>
        )}
        <Text style={{ 
          fontSize: 24, 
          fontWeight: 'bold', 
          color: textColor
        }}>
          {title}
        </Text>
      </View>
      {isHomeScreen && (
        <View style={{ flexDirection: 'row', gap: 12 }}>
          <TouchableOpacity 
            style={{ 
              width: 40,
              height: 40,
              borderRadius: 20,
              backgroundColor: 'rgba(255,255,255,0.2)', 
              justifyContent: 'center',
              alignItems: 'center',
              position: 'relative',
            }} 
            onPress={onNotificationPress}
          >
            <Icon name="bell" size={20} color="#fff" />
            {unreadNotifications > 0 && (
              <View style={{
                position: 'absolute',
                top: -2,
                right: -2,
                backgroundColor: '#EF4444',
                borderRadius: 10,
                minWidth: 20,
                height: 20,
                justifyContent: 'center',
                alignItems: 'center',
                paddingHorizontal: 4,
              }}>
                <Text style={{
                  color: '#FFFFFF',
                  fontSize: 10,
                  fontWeight: 'bold',
                }}>
                  {unreadNotifications}
                </Text>
              </View>
            )}
          </TouchableOpacity>
          <TouchableOpacity 
            style={{ 
              width: 36,
              height: 36,
              borderRadius: 18,
              backgroundColor: '#fff', 
              justifyContent: 'center',
              alignItems: 'center',
              overflow: 'hidden',
            }} 
            onPress={() => {
              console.log('Header: Profile button pressed, onProfilePress:', !!onProfilePress);
              if (onProfilePress) {
                onProfilePress();
              }
            }}
            activeOpacity={0.7}
          >
            <Text style={{
              fontSize: 16,
              fontWeight: 'bold',
              color: '#34d399',
            }}>
              {currentAccountAvatar}
            </Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}; 