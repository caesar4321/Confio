import React, { useEffect } from 'react';
import { ActivityIndicator, SafeAreaView, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';

import { BrebLocationGate } from '../components/breb/BrebLocationGate';
import { colors } from '../config/theme';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';

// The Bre-B location step, opened from the application's requirements (or to
// renew a lapsed check before showing a key): the permission screen the first
// time, then straight back to where the person came from.
export default function BrebLocationCheckScreen() {
  return (
    <BrebLocationGate>
      <Confirmed />
    </BrebLocationGate>
  );
}

function Confirmed() {
  const navigation = useNavigation<any>();
  useEffect(() => {
    navigation.goBack();
  }, [navigation]);
  return (
    <SafeAreaView style={styles.container}>
      <View style={[styles.loadingCard, { marginTop: 80 }]}>
        <ActivityIndicator color={colors.primary} />
        <Text style={styles.loadingText}>Ubicación confirmada</Text>
      </View>
    </SafeAreaView>
  );
}
