import React from 'react';
import { View, Text, TouchableOpacity, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList } from '../types/navigation';

export const HEADER_HEIGHT = Platform.OS === 'ios' ? 88 : 64;

interface HeaderProps {
  title: string;
  navigation: NativeStackNavigationProp<RootStackParamList>;
  isHomeScreen?: boolean;
  onProfilePress?: () => void;
  onNotificationPress?: () => void;
  backgroundColor?: string;
  isLight?: boolean;
  showBackButton?: boolean;
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
}; 