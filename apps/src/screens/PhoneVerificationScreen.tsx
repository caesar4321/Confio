import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Platform,
  KeyboardAvoidingView,
  TouchableWithoutFeedback,
  Keyboard,
  Modal,
  FlatList,
  SafeAreaView,
  ScrollView,
  Button,
  Alert,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Feather from 'react-native-vector-icons/Feather';
import TelegramLogo from '../assets/svg/TelegramLogo.svg';
import { countries, Country } from '../utils/countries';
import { useMutation } from '@apollo/client';
import { INITIATE_TELEGRAM_VERIFICATION, VERIFY_TELEGRAM_CODE, UPDATE_PHONE_NUMBER } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { useCountrySelection } from '../hooks/useCountrySelection';

type RootStackParamList = {
  Auth: undefined;
  PhoneVerification: undefined;
  Home: undefined;
};

type PhoneVerificationScreenNavigationProp = NativeStackNavigationProp<RootStackParamList, 'PhoneVerification'>;

const PhoneVerificationScreen = () => {
  const navigation = useNavigation<PhoneVerificationScreenNavigationProp>();
  const { handleSuccessfulLogin, userProfile, refreshProfile } = useAuth();
  const [phoneNumber, setPhoneNumber] = useState('');
  const { selectedCountry, showCountryModal, selectCountry, openCountryModal, closeCountryModal, setSelectedCountry } = useCountrySelection();
  const [verificationMethod, setVerificationMethod] = useState<'telegram' | 'sms' | null>(null);
  const [verificationCode, setVerificationCode] = useState<string[]>(['', '', '', '', '', '']);
  const [currentScreen, setCurrentScreen] = useState<'phone' | 'method' | 'code'>('phone');
  const phoneInputRef = useRef<TextInput>(null);
  const codeInputRefs = Array.from({ length: 6 }, () => useRef<TextInput>(null));
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'input' | 'code'>('input');

  const [initiateTelegramVerification, { loading: loadingInitiate }] = useMutation(INITIATE_TELEGRAM_VERIFICATION);
  const [verifyTelegramCode, { loading: loadingVerify }] = useMutation(VERIFY_TELEGRAM_CODE);
  const [updatePhoneNumber] = useMutation(UPDATE_PHONE_NUMBER);

  // Colors from the design
  const colors = {
    confioGreen: '#72D9BC',
    white: '#FFFFFF',
    accentPurple: '#8B5CF6',
    darkGray: '#1F2937',
    lightGray: '#F3F4F6',
    grayBorder: '#E5E7EB',
    grayText: '#6B7280',
    buttonDisabled: '#CDEFE5',
  };

  const handleBack = () => {
    if (currentScreen === 'method') {
      setCurrentScreen('phone');
    } else if (currentScreen === 'code') {
      setCurrentScreen('method');
    }
  };

  const handleContinue = async () => {
    if (currentScreen === 'phone') {
      setCurrentScreen('method');
    } else if (currentScreen === 'method') {
      setCurrentScreen('code');
    } else if (currentScreen === 'code') {
      await handleVerifyCode();
    }
  };

  const handleSendTelegramCode = async () => {
    try {
      const countryCode = selectedCountry?.[2] || 'VE'; // ISO country code (e.g., 'VE' for Venezuela)
      // Format phone number: remove any spaces, dashes, or other separators
      const cleanPhoneNumber = phoneNumber.replace(/[\s-]/g, '');
      console.log('Sending verification with:', { phoneNumber: cleanPhoneNumber, countryCode });
      
      const { data } = await initiateTelegramVerification({ 
        variables: { 
          phoneNumber: cleanPhoneNumber,
          countryCode
        } 
      });
      
      console.log('Verification response:', data);
      
      if (data.initiateTelegramVerification.success) {
        setStep('code');
        setCurrentScreen('code');
      } else {
        Alert.alert('Error', data.initiateTelegramVerification.error || 'Failed to send code');
      }
    } catch (e) {
      console.error('Error sending verification:', e);
      Alert.alert('Error', 'Network error');
    }
  };

  const handleVerifyCode = async () => {
    try {
      if (verificationMethod === 'telegram') {
        // Format phone number: remove any spaces, dashes, or other separators
        const cleanPhoneNumber = phoneNumber.replace(/[\s-]/g, '');
        
        const { data } = await verifyTelegramCode({ 
          variables: { 
              phoneNumber: cleanPhoneNumber,
              countryCode: selectedCountry?.[2] || 'VE', // ISO country code
              code: verificationCode.join('') // Join the code array into a single string
          } 
        });
        
        if (data.verifyTelegramCode.success) {
          // Check if we're in the profile update flow (user is already authenticated)
          const isProfileUpdateFlow = !!userProfile;
          
          if (isProfileUpdateFlow) {
            // Update the user's phone number in the database
            const { data: updateData } = await updatePhoneNumber({
              variables: {
                countryCode: selectedCountry?.[1] || '+58', // Phone code (e.g., '+58')
                phoneNumber: cleanPhoneNumber,
              },
            });
            
            if (updateData?.updatePhoneNumber?.success) {
              Alert.alert(
                'Éxito', 
                'Número de teléfono actualizado correctamente',
                [
                  {
                    text: 'OK',
                    onPress: () => {
                      // Refresh user profile and go back
                      refreshProfile('personal');
                      navigation.goBack();
                    }
                  }
                ]
              );
            } else {
              Alert.alert('Error', updateData?.updatePhoneNumber?.error || 'Failed to update phone number');
            }
          } else {
            // Auth flow - proceed with login
            Alert.alert('Success', 'Phone number verified!');
            await handleSuccessfulLogin(true);
          }
        } else {
          Alert.alert('Error', data.verifyTelegramCode.error || 'Verification failed');
        }
      } else if (verificationMethod === 'sms') {
        // TODO: Implement SMS verification once the mutation is available
        await handleSuccessfulLogin(true);
      } else {
        Alert.alert('Error', 'Invalid verification method');
      }
    } catch (e) {
      Alert.alert('Error', 'Network error');
    }
  };

  const renderCountryItem = ({ item }: { item: Country }) => (
    <TouchableOpacity
      style={styles.countryItem}
      onPress={() => selectCountry(item)}
    >
      <Text style={styles.flag}>{item[3]}</Text>
      <Text style={styles.countryName}>{item[0]}</Text>
      <Text style={styles.countryCode}>{item[1]}</Text>
    </TouchableOpacity>
  );

  const renderPhoneScreen = () => {
    const isProfileUpdateFlow = !!userProfile;
    const title = isProfileUpdateFlow ? 'Cambiar número de teléfono' : 'Ingresa tu número de teléfono';
    const subtitle = isProfileUpdateFlow 
      ? 'Ingresa tu nuevo número de teléfono para actualizar tu perfil'
      : 'Necesitamos verificar tu identidad para proteger tu cuenta';
    
    return (
    <View style={styles.screenContainer}>
      <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
        <Feather name="arrow-left" size={24} color={colors.darkGray} />
      </TouchableOpacity>

      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
      
      <Text style={styles.label}>País</Text>
      <TouchableOpacity
        style={styles.countrySelector}
        onPress={openCountryModal}
        activeOpacity={0.8}
      >
        <View style={styles.countrySelectorContent}>
          <Text style={styles.flag}>{selectedCountry?.[3] || '🌍'}</Text>
          <Text style={styles.countryName}>{selectedCountry?.[0] || 'Seleccionar país'}</Text>
        </View>
        <Feather name="chevron-down" size={22} color={colors.grayText} />
      </TouchableOpacity>

      <Text style={[styles.label, { marginTop: 24 }]}>Número de teléfono</Text>
      <View style={styles.phoneInputContainer}>
        <View style={styles.countryCodeBox}>
          <Text style={styles.countryCodeText}>{selectedCountry?.[1] || '+58'}</Text>
        </View>
        <TextInput
          ref={phoneInputRef}
          style={styles.phoneInput}
          placeholder="412 345 6789"
          keyboardType="phone-pad"
          value={phoneNumber}
          onChangeText={setPhoneNumber}
          maxLength={15}
          placeholderTextColor={colors.grayText}
        />
      </View>

      <TouchableOpacity
        style={[styles.continueButton, !phoneNumber && styles.continueButtonDisabled]}
        onPress={handleContinue}
        disabled={!phoneNumber}
      >
        <Text style={styles.continueButtonText}>Continuar</Text>
      </TouchableOpacity>

      <Text style={styles.supportingText}>
        {isProfileUpdateFlow 
          ? 'Tu nuevo número de teléfono se utilizará para verificación y para permitir que tus amigos te envíen dinero.'
          : 'Tu número de teléfono se utilizará para verificación y para permitir que tus amigos te envíen dinero. No será compartido con terceros.'
        }
      </Text>
    </View>
    );
  };

  const renderVerificationMethodScreen = () => {
    const isProfileUpdateFlow = !!userProfile;
    const title = isProfileUpdateFlow ? 'Verifica tu nuevo número' : 'Verifica tu número';
    const subtitle = isProfileUpdateFlow 
      ? `Selecciona cómo quieres verificar tu nuevo número\n<Text style={styles.phoneNumber}>${selectedCountry[1]} ${phoneNumber}</Text>`
      : `Selecciona cómo quieres verificar tu número\n<Text style={styles.phoneNumber}>${selectedCountry[1]} ${phoneNumber}</Text>`;
    
    return (
    <View style={styles.screenContainer}>
      <TouchableOpacity style={styles.backButton} onPress={handleBack}>
        <Feather name="arrow-left" size={24} color={colors.darkGray} />
      </TouchableOpacity>

      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>
        {isProfileUpdateFlow 
          ? `Selecciona cómo quieres verificar tu nuevo número\n`
          : `Selecciona cómo quieres verificar tu número\n`
        }
        <Text style={styles.phoneNumber}>{selectedCountry?.[1] || '+58'} {phoneNumber}</Text>
      </Text>

      <View style={styles.methodContainer}>
        <TouchableOpacity
          style={styles.methodCard}
          activeOpacity={0.85}
          onPress={() => {
            setVerificationMethod('telegram');
            handleSendTelegramCode();
          }}
        >
          <View style={styles.methodIconContainer}>
            <TelegramLogo width="100%" height="100%" />
          </View>
          <View style={styles.methodContent}>
            <Text style={styles.methodTitle}>Verificación vía Telegram</Text>
            <Text style={styles.methodDescription}>Enviaremos un código a tu cuenta de Telegram</Text>
            <View style={styles.methodButtonRow}>
              <Text style={styles.methodButtonText}>Enviar código</Text>
              <Feather name="arrow-right" size={16} color={colors.confioGreen} />
            </View>
          </View>
        </TouchableOpacity>
      </View>

      <TouchableOpacity
        style={styles.smsButton}
        onPress={() => {
          setVerificationMethod('sms');
          handleContinue();
        }}
      >
        <Text style={styles.smsButtonText}>Recibir a través de SMS</Text>
        <Feather name="arrow-right" size={16} color="#6B7280" />
      </TouchableOpacity>
    </View>
    );
  };

  const renderVerificationCodeScreen = () => {
    const isProfileUpdateFlow = !!userProfile;
    const title = isProfileUpdateFlow ? 'Verifica tu nuevo número' : 'Ingresa el código';
    const subtitle = isProfileUpdateFlow 
      ? `${verificationMethod === 'telegram' ? 'Enviamos un código a tu Telegram' : 'Enviamos un código por SMS'} para verificar tu nuevo número\n`
      : `${verificationMethod === 'telegram' ? 'Enviamos un código a tu Telegram' : 'Enviamos un código por SMS'} al número\n`;
    
    return (
    <View style={styles.screenContainer}>
      <TouchableOpacity style={styles.backButton} onPress={handleBack}>
        <Feather name="arrow-left" size={24} color={colors.darkGray} />
      </TouchableOpacity>

      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>
        {subtitle}
        <Text style={styles.phoneNumber}>{selectedCountry?.[1] || '+58'} {phoneNumber}</Text>
      </Text>

      <View style={styles.codeContainer}>
        {verificationCode.map((digit, index) => (
          <TextInput
            key={index}
            ref={codeInputRefs[index]}
            style={styles.codeInput}
            maxLength={1}
            keyboardType="number-pad"
            value={digit}
            onChangeText={(value) => {
              const newCode = [...verificationCode];
              newCode[index] = value;
              setVerificationCode(newCode);
              if (value && index < 5) {
                codeInputRefs[index + 1].current?.focus();
              }
            }}
            onKeyPress={({ nativeEvent }) => {
              if (nativeEvent.key === 'Backspace' && !verificationCode[index] && index > 0) {
                codeInputRefs[index - 1].current?.focus();
              }
            }}
            returnKeyType={index === 5 ? 'done' : 'next'}
          />
        ))}
      </View>

      <TouchableOpacity
        style={[styles.continueButton, verificationCode.join('').length !== 6 && styles.continueButtonDisabled]}
        onPress={handleContinue}
        disabled={verificationCode.join('').length !== 6}
      >
        <Text style={styles.continueButtonText}>Verificar</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.resendButton}>
        <Text style={styles.resendButtonText}>¿No recibiste el código? </Text>
        <Text style={[styles.resendButtonText, { color: colors.confioGreen }]}>Reenviar código</Text>
      </TouchableOpacity>
    </View>
    );
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={{ flex: 1 }}
      keyboardVerticalOffset={0}
    >
      <SafeAreaView style={styles.safeArea}>
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <ScrollView
            style={styles.container}
            contentContainerStyle={{ flexGrow: 1 }}
            keyboardShouldPersistTaps="handled"
          >
            {currentScreen === 'phone' && renderPhoneScreen()}
            {currentScreen === 'method' && renderVerificationMethodScreen()}
            {currentScreen === 'code' && renderVerificationCodeScreen()}
          </ScrollView>
        </TouchableWithoutFeedback>
      </SafeAreaView>

      <Modal
        visible={showCountryModal}
        transparent={true}
        animationType="slide"
        onRequestClose={closeCountryModal}
      >
        <View style={styles.modalContainer}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Selecciona un país</Text>
              <TouchableOpacity onPress={closeCountryModal}>
                <Feather name="x" size={24} color={colors.darkGray} />
              </TouchableOpacity>
            </View>
            <FlatList
              data={countries}
              renderItem={renderCountryItem}
              keyExtractor={(item) => item[2]}
              style={styles.countryList}
            />
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  keyboardAvoidingView: {
    flex: 1,
  },
  content: {
    flex: 1,
    padding: 20,
  },
  screenContainer: {
    flex: 1,
    padding: 20,
  },
  backButton: {
    marginBottom: 24,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#1F2937',
    marginBottom: 32,
    lineHeight: 24,
  },
  phoneNumber: {
    fontWeight: '500',
  },
  label: {
    fontSize: 15,
    color: '#1F2937',
    marginBottom: 8,
    fontWeight: '500',
  },
  countrySelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#FFFFFF',
    borderColor: '#E5E7EB',
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  countrySelectorContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  flag: {
    fontSize: 22,
    marginRight: 10,
  },
  countryName: {
    fontSize: 16,
    color: '#1F2937',
    fontWeight: '500',
  },
  countryCode: {
    fontSize: 15,
    color: '#6B7280',
    marginLeft: 'auto',
  },
  phoneInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderColor: '#E5E7EB',
    borderWidth: 1,
    borderRadius: 16,
    marginBottom: 24,
  },
  countryCodeBox: {
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: '#FFFFFF',
    borderTopLeftRadius: 16,
    borderBottomLeftRadius: 16,
    borderRightWidth: 1,
    borderRightColor: '#E5E7EB',
  },
  countryCodeText: {
    fontSize: 16,
    color: '#1F2937',
    fontWeight: '500',
  },
  phoneInput: {
    flex: 1,
    paddingVertical: 14,
    paddingHorizontal: 16,
    fontSize: 16,
    color: '#6B7280',
    borderTopRightRadius: 16,
    borderBottomRightRadius: 16,
  },
  continueButton: {
    backgroundColor: '#72D9BC',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 24,
  },
  continueButtonDisabled: {
    backgroundColor: '#D1D5DB',
  },
  continueButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  supportingText: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
  },
  methodContainer: {
    marginBottom: 24,
  },
  methodCard: {
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  methodIconContainer: {
    backgroundColor: '#72D9BC',
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  methodContent: {
    flex: 1,
  },
  methodTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 4,
  },
  methodDescription: {
    fontSize: 14,
    color: '#1F2937',
    marginBottom: 8,
  },
  methodButtonRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  methodButtonText: {
    color: '#72D9BC',
    fontSize: 14,
    fontWeight: '600',
    marginRight: 4,
  },
  smsButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 'auto',
  },
  smsButtonText: {
    color: '#6B7280',
    fontSize: 14,
  },
  codeContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 24,
  },
  codeInput: {
    width: 48,
    height: 56,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 8,
    textAlign: 'center',
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  resendButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  resendButtonText: {
    fontSize: 14,
    color: '#6B7280',
  },
  modalContainer: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
  },
  countryList: {
    maxHeight: 400,
  },
  countryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  safeArea: {
    flex: 1,
  },
});

export default PhoneVerificationScreen; 