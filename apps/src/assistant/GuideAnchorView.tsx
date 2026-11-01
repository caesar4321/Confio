// For targets that aren't our own pressables, such as a tab bar icon.
import React from 'react';
import { View } from 'react-native';
import { useGuideAnchor } from './guidePointer';

export default function GuideAnchorView({ id, children }: { id: string; children: React.ReactNode }) {
  const anchor = useGuideAnchor(id);
  return <View ref={anchor} collapsable={false}>{children}</View>;
}
