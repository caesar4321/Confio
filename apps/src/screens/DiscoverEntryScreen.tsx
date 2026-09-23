import React from 'react';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';

/** Compatibility entry for notifications and existing stack-level feed links. */
export const DiscoverEntryScreen = ({ navigation }: NativeStackScreenProps<MainStackParamList, 'Discover'>) => {
  React.useLayoutEffect(() => {
    navigation.popTo('BottomTabs', { screen: 'Discover' });
  }, [navigation]);
  return null;
};
