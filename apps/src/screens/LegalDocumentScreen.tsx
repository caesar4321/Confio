import React from 'react';
import { useRoute, useNavigation, NavigationProp } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { LegalDocumentView, RouteParams } from '../components/LegalDocumentView';
import { colors } from '../config/theme';

const LegalDocumentScreen = () => {
  const route = useRoute();
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const { docType } = route.params as RouteParams;
  return (
    <LegalDocumentView
      docType={docType}
      renderHeader={(title) => (
        <Header title={title} navigation={navigation} backgroundColor={colors.background} isLight={false} />
      )}
    />
  );
};

export default LegalDocumentScreen;
