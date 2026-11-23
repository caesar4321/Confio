// The shared Header for a screen opened from the drawer: ☰ where a pushed
// screen has its back arrow, and a way back to Inicio on the right (without
// a tab bar, and with no hardware back on iOS, it must be one tap away).
// On the brand field everything is drawn in the field's dark ink, like
// Inicio's own header; each such screen draws its hero text in the same ink.
import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { logHomeNav } from '../services/homeNavAnalytics';
import { useAppDrawer } from './AppDrawer';

type Props = {
  title: string;
  backgroundColor: string;
  /** The header sits on the brand field. */
  isLight?: boolean;
};

export function DrawerHeader({ title, backgroundColor, isLight = false }: Props) {
  const navigation = useNavigation<any>();
  const drawer = useAppDrawer();
  const ink = isLight ? colors.onHeroField : '#1F2937';
  return (
    <Header
      navigation={navigation}
      title={title}
      backgroundColor={backgroundColor}
      isLight={isLight}
      ink={isLight ? colors.onHeroField : undefined}
      showBackButton={false}
      onMenuPress={drawer.open}
      menuDot={drawer.hasNews}
      rightAccessory={(
        <Pressable
          onPress={() => {
            logHomeNav('header', 'home');
            drawer.goHome();
          }}
          style={[styles.home, isLight ? styles.homeOnField : styles.homeOnWhite]}
          hitSlop={4}
          accessibilityRole="button"
          accessibilityLabel="Inicio"
        >
          <Icon name="home" size={20} color={ink} />
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  home: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  homeOnField: { backgroundColor: 'rgba(255,255,255,0.35)' },
  homeOnWhite: { backgroundColor: '#F3F4F6' },
});
