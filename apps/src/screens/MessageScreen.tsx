import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { MessageInboxContent } from '../components/MessageInboxContent';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { describeTypes, logBreadcrumb } from '../services/crashLog';
import { colors } from '../config/theme';
import { useOptionalConfioIa } from '../assistant/ConfioIaContext';


export const MessageScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const route = useRoute<any>();
  const [screenState, setScreenState] = useState<'inbox' | 'channel'>('inbox');
  const initialChannelId = route.params?.initialChannelId;
  const confioIa = useOptionalConfioIa();

  // Mensajes lives in the floating box now. Pushes and confio://messages/…
  // links still land on this route: hand them to the box and step back.
  useEffect(() => {
    if (!confioIa) {
      return;
    }
    // 'ia' shows Confío IA, or the classic support thread when it's unavailable.
    const channel = initialChannelId === 'julian' || initialChannelId === 'confio' ? initialChannelId : 'ia';
    confioIa.open({ channel });
    if (navigation.canGoBack()) {
      navigation.goBack();
    } else {
      navigation.navigate('BottomTabs' as any);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    logBreadcrumb(
      `MessageScreen.mount | ${describeTypes({ initialChannelId })}`
    );
    return () => {
      logBreadcrumb('MessageScreen.unmount');
    };
  }, []);

  useEffect(() => {
    logBreadcrumb(`MessageScreen.screenState | state=${screenState}`);
  }, [screenState]);

  if (confioIa) {
    return <View style={styles.container} />;
  }

  return (
    <View style={styles.container}>
      {screenState === 'inbox' && (
        <Header
          title="Mensajes"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor={colors.heroField}
          isLight
        />
      )}
      <MessageInboxContent onScreenStateChange={setScreenState} initialChannelId={initialChannelId} />
    </View>
  );
};

export default MessageScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
});
