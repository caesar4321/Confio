import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';

import { DirectInboxContent } from '../components/DirectInboxContent';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { useOptionalAssistant } from '../assistant/AssistantContext';
import { MainStackParamList } from '../types/navigation';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'DirectInbox'>['route'];

/**
 * Mensajes lives in the assistant box (its own chat head). Pushes and links
 * still land on this route: hand them to the box and step back. Without the
 * box, the list is shown here.
 */
export const DirectInboxScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const assistant = useOptionalAssistant();
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!assistant) return;
    assistant.open({ channel: 'mensajes', dmFolder: route.params?.folder });
    if (navigation.canGoBack()) navigation.goBack();
    else navigation.navigate('BottomTabs' as any);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFocusEffect(useCallback(() => { setRefreshKey((k) => k + 1); }, []));

  if (assistant) return <View style={styles.container} />;

  return (
    <View style={styles.container}>
      <Header title="Mensajes" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <DirectInboxContent
        initialFolder={route.params?.folder ?? 'inbox'}
        refreshKey={refreshKey}
        onOpenConversation={(c) => navigation.navigate('DirectChat', { conversationId: c.id, username: c.other.username })}
      />
    </View>
  );
};

export default DirectInboxScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
});
