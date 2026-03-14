import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { MessageInboxContent } from '../components/MessageInboxContent';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';


export const MessageScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const route = useRoute<any>();
  const [screenState, setScreenState] = useState<'inbox' | 'channel'>('inbox');
  const initialChannelId = route.params?.initialChannelId;

  return (
    <View style={styles.container}>
      {screenState === 'inbox' && (
        <Header
          title="Mensajes"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor="#34d399"
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
    backgroundColor: '#F9FAFB',
  },
});
