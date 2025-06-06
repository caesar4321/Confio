import { NativeStackNavigationProp } from '@react-navigation/native-stack';

export type RootStackParamList = {
  Auth: undefined;
  Main: undefined;
  PhoneVerification: undefined;
  LegalDocument: {
    docType: 'terms' | 'privacy' | 'deletion';
  };
  Verification: undefined;
};

export type BottomTabParamList = {
  Home: undefined;
  Contacts: undefined;
  Scan: undefined;
  Exchange: undefined;
  Profile: undefined;
}; 

export type RootStackNavigationProp = NativeStackNavigationProp<RootStackParamList>; 