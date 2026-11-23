// "Invitar y ganar": the referral programme on a screen of its own, opened
// from the last row of the menu and from Perfil.
import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { ReferralProgramCard } from '../components/ReferralProgramCard';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';

export default function InviteScreen() {
  const navigation = useNavigation();
  return (
    <View style={styles.screen}>
      <Header navigation={navigation as any} title="Invitar y ganar" backgroundColor={colors.heroField} isLight showBackButton />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <ReferralProgramCard surface="invite" />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  content: { paddingTop: 16, paddingBottom: 24 },
});
