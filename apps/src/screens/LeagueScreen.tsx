import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';

import { LeagueContent } from '../components/LeagueContent';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'League'>['route'];

/** The league on its own screen (links from a profile badge); its home is the row at the top of Comunidad. */
export const LeagueScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  return (
    <View style={styles.container}>
      <Header title="Liga Confío" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <LeagueContent initialKind={route.params?.kind ?? 'teams'} />
    </View>
  );
};

export default LeagueScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
});
