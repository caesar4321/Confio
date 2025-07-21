import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Modal,
  TouchableWithoutFeedback,
  Keyboard,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { useCurrency } from '../hooks/useCurrency';
import { getApiUrl } from '../config/env';
import { useAuth } from '../contexts/AuthContext';

type TradeChatRouteProp = RouteProp<MainStackParamList, 'TradeChat'>;
type TradeChatNavigationProp = NativeStackNavigationProp<MainStackParamList, 'TradeChat'>;

interface Message {
  id: number;
  sender: 'system' | 'trader' | 'user';
  text: string;
  timestamp: Date;
  type: 'system' | 'text' | 'payment_info';
}

interface Trader {
  name: string;
  isOnline: boolean;
  verified: boolean;
  lastSeen: string;
  responseTime: string;
}

interface TradeData {
  amount: string;
  crypto: string;
  totalBs: string;
  paymentMethod: string;
  rate: string;
}

export const TradeChatScreen: React.FC = () => {
  const navigation = useNavigation<TradeChatNavigationProp>();
  const route = useRoute<TradeChatRouteProp>();
  const { offer, crypto, amount, tradeType, tradeId } = route.params;
  const { userProfile } = useAuth();
  
  // Currency formatting
  const { formatAmount } = useCurrency();
  
  const [message, setMessage] = useState('');
  const [currentTradeStep, setCurrentTradeStep] = useState(1);
  const [timeRemaining, setTimeRemaining] = useState(900); // 15 minutes in seconds
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [typingUser, setTypingUser] = useState<string | null>(null);
  const [isSecurityNoticeDismissed, setIsSecurityNoticeDismissed] = useState(false);

  const messagesEndRef = useRef<ScrollView>(null);
  const websocket = useRef<WebSocket | null>(null);

  // WebSocket connection
  useEffect(() => {
    if (!tradeId) {
      // Fallback to mock data if no tradeId (for development/testing)
      console.warn('No tradeId provided, using mock data');
      setMessages([
        {
          id: 1,
          sender: 'system',
          text: 'Intercambio iniciado. Tienes 15 minutos para completar el pago.',
          timestamp: new Date(Date.now() - 300000),
          type: 'system'
        },
        {
          id: 2,
          sender: 'trader',
          text: '¡Hola! Gracias por elegir mi oferta. Te envío los datos para el pago.',
          timestamp: new Date(Date.now() - 270000),
          type: 'text'
        },
        {
          id: 3,
          sender: 'user',
          text: 'Perfecto, estoy listo para hacer el pago.',
          timestamp: new Date(Date.now() - 240000),
          type: 'text'
        },
        {
          id: 4,
          sender: 'trader',
          text: 'Te envío los datos bancarios por aquí.',
          timestamp: new Date(Date.now() - 210000),
          type: 'text'
        },
        {
          id: 5,
          sender: 'user',
          text: 'Recibido, procesando el pago ahora.',
          timestamp: new Date(Date.now() - 180000),
          type: 'text'
        }
      ]);
      setIsConnected(false);
      return;
    }

    const connectWebSocket = async () => {
      try {
        console.log('🔄 Attempting WebSocket connection...');
        
        // Get JWT token from Keychain
        const Keychain = require('react-native-keychain');
        const { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } = require('../services/authService');
        
        console.log('🔑 Retrieving token from Keychain...');
        const credentials = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        
        let token = '';
        if (credentials) {
          try {
            const tokens = JSON.parse(credentials.password);
            token = tokens.accessToken || '';
            console.log('✅ Token retrieved successfully:', token ? 'Token found' : 'No token');
          } catch (error) {
            console.error('❌ Error parsing tokens for WebSocket:', error);
          }
        } else {
          console.log('⚠️ No credentials found in Keychain');
        }
        
        if (!token) {
          console.error('❌ No JWT token available, WebSocket connection may fail');
          setIsConnected(false);
          return;
        }
        
        // Convert HTTP API URL to WebSocket URL
        const apiUrl = getApiUrl();
        console.log('🔧 Original API URL:', apiUrl);
        // Remove /graphql/ path and convert protocol
        const wsBaseUrl = apiUrl.replace('http://', 'ws://').replace('https://', 'wss://').replace('/graphql/', '/');
        const wsUrl = `${wsBaseUrl}ws/trade/${tradeId}/?token=${encodeURIComponent(token)}`;
        console.log('🌐 Connecting to WebSocket:', `${wsBaseUrl}ws/trade/${tradeId}/?token=TOKEN_HIDDEN`);
        console.log('🔍 Full WebSocket URL (sanitized):', wsUrl.replace(token, 'TOKEN_HIDDEN'));
        
        websocket.current = new WebSocket(wsUrl);
        
        websocket.current.onopen = () => {
          console.log('✅ WebSocket connected successfully');
          setIsConnected(true);
        };
        
        websocket.current.onmessage = (event) => {
          console.log('📨 WebSocket message received:', event.data);
          try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
          } catch (error) {
            console.error('❌ Error parsing WebSocket message:', error);
          }
        };
        
        websocket.current.onclose = (event) => {
          console.log('❌ WebSocket disconnected:', event.code, event.reason);
          console.log('📊 Close event details:', {
            code: event.code,
            reason: event.reason,
            wasClean: event.wasClean,
            type: event.type
          });
          setIsConnected(false);
          
          // Only reconnect if it wasn't a deliberate close
          if (event.code !== 1000) {
            console.log('🔄 Attempting to reconnect in 3 seconds...');
            setTimeout(() => {
              if (!websocket.current || websocket.current.readyState === WebSocket.CLOSED) {
                connectWebSocket();
              }
            }, 3000);
          }
        };
        
        websocket.current.onerror = (error) => {
          console.error('❌ WebSocket error:', error);
          console.log('🐛 Error details:', {
            message: error.message,
            type: error.type,
            target: error.target
          });
          setIsConnected(false);
        };
        
      } catch (error) {
        console.error('Failed to create WebSocket connection:', error);
        Alert.alert('Error de conexión', 'No se pudo conectar al chat. Intenta de nuevo.');
      }
    };

    connectWebSocket();

    // Cleanup on unmount
    return () => {
      if (websocket.current) {
        websocket.current.close();
      }
    };
  }, [tradeId]);

  // Handle WebSocket messages
  const handleWebSocketMessage = (data: any) => {
    switch (data.type) {
      case 'chat_history':
        setMessages(data.messages.map((msg: any) => ({
          id: msg.id,
          sender: msg.sender.id === userProfile?.id ? 'user' : 'trader',
          text: msg.content,
          timestamp: new Date(msg.createdAt),
          type: msg.messageType.toLowerCase()
        })));
        break;
        
      case 'chat_message':
        const newMessage: Message = {
          id: data.message.id,
          sender: data.message.sender.id === userProfile?.id ? 'user' : 'trader',
          text: data.message.content,
          timestamp: new Date(data.message.createdAt),
          type: data.message.messageType.toLowerCase()
        };
        
        // Update existing temporary message with server data or add new message
        setMessages(prev => {
          // First check if this is a server confirmation of our sent message
          const tempMessageIndex = prev.findIndex(msg => 
            msg.sender === newMessage.sender && 
            msg.text === newMessage.text && 
            typeof msg.id === 'number' && // Temporary IDs are numbers (timestamp)
            Math.abs(msg.timestamp.getTime() - newMessage.timestamp.getTime()) < 10000
          );
          
          if (tempMessageIndex >= 0) {
            // Replace temporary message with server message
            const updated = [...prev];
            updated[tempMessageIndex] = newMessage;
            return updated;
          }
          
          // Check if message already exists (prevent true duplicates)
          const exists = prev.some(msg => msg.id === newMessage.id);
          if (exists) {
            return prev;
          }
          
          return [...prev, newMessage];
        });
        break;
        
      case 'typing_indicator':
        if (data.user_id !== userProfile?.id) {
          setTypingUser(data.is_typing ? data.username : null);
        }
        break;
        
      case 'trade_status_update':
        // Handle trade status updates
        console.log('Trade status updated:', data.status);
        break;
        
      case 'error':
        Alert.alert('Error', data.message);
        break;
    }
  };

  // Send message via WebSocket
  const sendWebSocketMessage = (content: string) => {
    if (websocket.current && websocket.current.readyState === WebSocket.OPEN) {
      websocket.current.send(JSON.stringify({
        type: 'chat_message',
        message: content
      }));
    }
  };

  // Send typing indicator
  const sendTypingIndicator = (isTyping: boolean) => {
    if (websocket.current && websocket.current.readyState === WebSocket.OPEN) {
      websocket.current.send(JSON.stringify({
        type: 'typing',
        isTyping: isTyping
      }));
    }
  };

  // Trader data from route params
  const trader: Trader = {
    name: offer.name,
    isOnline: offer.isOnline,
    verified: offer.verified,
    lastSeen: offer.lastSeen,
    responseTime: offer.responseTime
  };

  // Trade data calculated from route params
  const tradeData: TradeData = {
    amount: amount,
    crypto: crypto,
    totalBs: formatAmount.withCode(parseFloat(amount) * parseFloat(offer.rate)),
    paymentMethod: (offer.paymentMethods[0]?.displayName || offer.paymentMethods[0]?.name) || 'Banco Venezuela',
    rate: offer.rate
  };

  // Timer effect
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeRemaining(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          Alert.alert('Tiempo Expirado', 'El tiempo para completar el pago ha expirado.');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Debug messages state
  useEffect(() => {
    console.log('📨 Messages updated:', messages.length, 'messages');
    console.log('📨 Current user ID:', userProfile?.id);
    messages.forEach((msg, index) => {
      console.log(`📨 Message ${index}:`, {
        id: msg.id,
        sender: msg.sender,
        text: msg.text.substring(0, 30) + '...',
        isUser: msg.sender === 'user'
      });
    });
  }, [messages]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        messagesEndRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  }, [messages]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const getStepText = (step: number) => {
    const steps: { [key: number]: string } = {
      1: "Realizar pago",
      2: "Confirmar pago", 
      3: "Esperando verificación",
      4: "Completado"
    };
    return steps[step] || "En proceso";
  };

  const handleGoBack = () => {
    // Navigate back to Exchange screen with active trades tab
    navigation.navigate('BottomTabs', { screen: 'Exchange' });
  };

  const handleAbandonTrade = () => {
    Alert.alert(
      '¿Abandonar intercambio?',
      'Esta acción cancelará el intercambio y no podrás recuperarlo. ¿Estás seguro?',
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Abandonar',
          style: 'destructive',
          onPress: () => {
            // Here you would typically call an API to cancel the trade
            Alert.alert('Intercambio cancelado', 'El intercambio ha sido cancelado.');
            navigation.navigate('BottomTabs', { screen: 'Exchange' });
          },
        },
      ]
    );
  };

  const handleViewTrade = () => {
    // Navigate to trade details or back to exchange
    navigation.navigate('BottomTabs', { screen: 'Exchange' });
  };

  const [showConfirmPaidModal, setShowConfirmPaidModal] = useState(false);

  const handleMarkAsPaid = () => {
    setShowConfirmPaidModal(true);
  };

  const confirmMarkAsPaid = () => {
    setShowConfirmPaidModal(false);
    if (currentTradeStep === 1) {
      setCurrentTradeStep(2);
      const systemMessage: Message = {
        id: messages.length + 1,
        sender: 'system',
        text: 'Usuario marcó el pago como completado',
        timestamp: new Date(),
        type: 'system',
      };
      setMessages(prev => [...prev, systemMessage]);
    }
  };

  const handleSendMessage = () => {
    if (message.trim() && isConnected) {
      // Immediately add the message to local state for better UX
      const tempMessage: Message = {
        id: Date.now(), // Temporary ID
        sender: 'user',
        text: message.trim(),
        timestamp: new Date(),
        type: 'text'
      };
      setMessages(prev => [...prev, tempMessage]);
      
      sendWebSocketMessage(message.trim());
      setMessage('');
      
      // Stop typing indicator
      sendTypingIndicator(false);
    } else if (!isConnected) {
      Alert.alert('Sin conexión', 'No hay conexión al chat. Intenta de nuevo.');
    }
  };

  const formatTimestamp = (timestamp: Date) => {
    return timestamp.toLocaleTimeString('es-VE', { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  const MessageBubble: React.FC<{ msg: Message }> = ({ msg }) => {
    const isUser = msg.sender === 'user';
    const isSystem = msg.sender === 'system';
    const isPaymentInfo = msg.type === 'payment_info';

    if (isSystem) {
      return (
        <View style={styles.systemMessageContainer}>
          <View style={styles.systemMessage}>
            <Icon name="info" size={12} color={colors.accent} style={styles.systemIcon} />
            <Text style={styles.systemMessageText}>{msg.text}</Text>
          </View>
        </View>
      );
    }

    if (isPaymentInfo) {
      const isPaymentFromUser = msg.sender === 'user';
      return (
        <View style={[styles.paymentInfoContainer, isPaymentFromUser ? styles.userPaymentInfoContainer : styles.traderPaymentInfoContainer]}>
          <View style={[styles.paymentInfoBubble, isPaymentFromUser ? styles.userPaymentInfoBubble : styles.traderPaymentInfoBubble]}>
            <View style={styles.paymentInfoHeader}>
              <Icon name="check-circle" size={16} color={isPaymentFromUser ? '#ffffff' : colors.success} style={styles.paymentIcon} />
              <Text style={[styles.paymentInfoTitle, isPaymentFromUser && styles.userPaymentInfoTitle]}>Datos de pago</Text>
            </View>
            <Text style={[styles.paymentInfoText, isPaymentFromUser && styles.userPaymentInfoText]}>{msg.text}</Text>
            <Text style={[styles.paymentInfoTimestamp, isPaymentFromUser && styles.userPaymentInfoTimestamp]}>
              {formatTimestamp(msg.timestamp)}
            </Text>
          </View>
        </View>
      );
    }

    return (
      <View style={[styles.messageContainer, isUser ? styles.userMessageContainer : styles.traderMessageContainer]}>
        <View style={[styles.messageBubble, isUser ? styles.userMessageBubble : styles.traderMessageBubble]}>
          <Text style={[styles.messageText, isUser ? styles.userMessageText : styles.traderMessageText]}>
            {msg.text}
          </Text>
          <Text style={[styles.messageTimestamp, isUser ? styles.userMessageTimestamp : styles.traderMessageTimestamp]}>
            {formatTimestamp(msg.timestamp)}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      {/* Header */}
      <View style={styles.headerRow}>
        {/* Left: Back Button */}
        <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#374151" />
        </TouchableOpacity>

        {/* Center: Trader Info */}
        <View style={styles.headerCenter}>
          <View style={styles.traderInfo}>
            <View style={styles.avatarContainer}>
              <Text style={styles.avatarText}>{trader.name.charAt(0)}</Text>
              {trader.isOnline && <View style={styles.onlineIndicator} />}
            </View>
            <View style={styles.traderDetails}>
              <View style={styles.traderNameRow}>
                <Text style={styles.traderName}>{trader.name}</Text>
                {trader.verified && (
                  <Icon name="shield" size={16} color={colors.accent} style={styles.verifiedIcon} />
                )}
              </View>
              <View style={styles.traderStatus}>
                <Icon 
                  name={isConnected ? "wifi" : "wifi-off"} 
                  size={12} 
                  color={isConnected ? "#10B981" : "#EF4444"} 
                  style={styles.statusIcon} 
                />
                <Text style={styles.statusText}>
                  {isConnected ? 'Chat conectado' : 'Conectando...'}
                </Text>
                {typingUser && (
                  <Text style={styles.typingText}>• {typingUser} está escribiendo...</Text>
                )}
              </View>
            </View>
          </View>
        </View>

        {/* Right: Abandonar Button */}
        <TouchableOpacity 
          style={styles.abandonButton}
          onPress={handleAbandonTrade}
        >
          <Text style={styles.abandonButtonText}>Abandonar</Text>
        </TouchableOpacity>
      </View>

      {/* Trade Status Banner */}
      <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
        <View style={styles.tradeStatusBanner}>
          <View style={styles.tradeStatusHeader}>
            <View style={styles.tradeInfo}>
              <Icon name="trending-up" size={16} color={colors.primary} style={styles.tradeIcon} />
              <Text style={styles.tradeAmount}>
                {tradeType === 'buy' ? `${tradeData.amount} ${tradeData.crypto} por ${tradeData.totalBs} Bs.` : `${tradeData.totalBs} Bs. por ${tradeData.amount} ${tradeData.crypto}`}
              </Text>
            </View>
            <View style={styles.tradeProgress}>
              <Text style={styles.stepIndicator}>Paso {currentTradeStep}/4</Text>
              <View style={styles.timerBadge}>
                <Text style={styles.timerText}>{formatTime(timeRemaining)}</Text>
              </View>
            </View>
          </View>
          
          <View style={styles.tradeStatusFooter}>
            <Text style={styles.stepText}>{getStepText(currentTradeStep)}</Text>
            <View style={styles.progressBar}>
              <View 
                style={[styles.progressFill, { width: `${(currentTradeStep / 4) * 100}%` }]} 
              />
            </View>
          </View>
        </View>
      </TouchableWithoutFeedback>

      {/* Quick Actions */}
      {currentTradeStep === 1 && (
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <View style={styles.paymentActionBanner}>
            <View style={styles.paymentActionContent}>
              <View style={styles.paymentActionInfo}>
                <Icon name="credit-card" size={16} color="#2563EB" style={styles.paymentActionIcon} />
                <Text style={styles.paymentActionText}>¿Ya realizaste el pago?</Text>
              </View>
              <TouchableOpacity onPress={handleMarkAsPaid} style={styles.markAsPaidButton}>
                <Text style={styles.markAsPaidButtonText}>Marcar como pagado</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableWithoutFeedback>
      )}

      {/* Security Notice */}
      {!isSecurityNoticeDismissed && (
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <View style={styles.securityNotice}>
            <View style={styles.securityContent}>
              <Icon name="alert-triangle" size={16} color="#D97706" style={styles.securityIcon} />
              <View style={styles.securityTextContainer}>
                <Text style={styles.securityTitle}>Seguridad:</Text>
                <Text style={styles.securityText}>• Solo comparte información bancaria en este chat seguro</Text>
                <Text style={styles.securityText}>• Nunca envíes criptomonedas antes de confirmar el pago</Text>
                <Text style={styles.securityText}>• No compartas comprobantes por fotos (vulnerables a edición)</Text>
              </View>
            </View>
            <TouchableOpacity 
              onPress={() => setIsSecurityNoticeDismissed(true)} 
              style={styles.securityDismissButton}
            >
              <Text style={styles.securityDismissButtonText}>Entiendo</Text>
            </TouchableOpacity>
          </View>
        </TouchableWithoutFeedback>
      )}

      {/* Messages and Input Container */}
      <KeyboardAvoidingView 
        style={styles.chatContainer} 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={0}
      >
        {/* Messages Area */}
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <ScrollView 
            ref={messagesEndRef}
            style={styles.messagesScroll}
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.messagesContent}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="on-drag"
          >
          {messages.length === 0 ? (
            <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
              <Text style={{ color: '#6B7280', fontStyle: 'italic' }}>
                No hay mensajes aún...
              </Text>
            </View>
          ) : (
            <>
              <View style={{ flex: 1 }} />
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
            </>
          )}
          </ScrollView>
        </TouchableWithoutFeedback>

        {/* Message Input */}
        <TouchableWithoutFeedback>
          <View style={styles.inputContainer}>
        <View style={styles.inputRow}>
          <View style={styles.inputWrapper}>
            <TextInput
              style={styles.textInput}
              value={message}
              onChangeText={(text) => {
                setMessage(text);
                
                // Send typing indicator
                if (text.trim() && !isTyping) {
                  setIsTyping(true);
                  sendTypingIndicator(true);
                  
                  // Stop typing after 2 seconds of no typing
                  setTimeout(() => {
                    setIsTyping(false);
                    sendTypingIndicator(false);
                  }, 2000);
                } else if (!text.trim() && isTyping) {
                  setIsTyping(false);
                  sendTypingIndicator(false);
                }
              }}
              placeholder="Escribe un mensaje..."
              placeholderTextColor="#9CA3AF"
              multiline
              maxLength={500}
            />
          </View>
          
          <TouchableOpacity 
            onPress={handleSendMessage}
            disabled={!message.trim()}
            style={[styles.sendButton, !message.trim() && styles.sendButtonDisabled]}
          >
            <Icon 
              name="send" 
              size={20} 
              color={message.trim() ? '#ffffff' : '#9CA3AF'} 
            />
          </TouchableOpacity>
        </View>
        </View>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>

      {/* Confirmation Modal for Marcar como pagado */}
      <Modal
        visible={showConfirmPaidModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowConfirmPaidModal(false)}
      >
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'center', alignItems: 'center' }}>
          <View style={{ backgroundColor: '#fff', borderRadius: 16, padding: 24, width: '80%', alignItems: 'center' }}>
            <Icon name="alert-triangle" size={32} color="#F59E42" style={{ marginBottom: 12 }} />
            <Text style={{ fontWeight: 'bold', fontSize: 18, marginBottom: 8 }}>¿Confirmar que realizaste el pago?</Text>
            <Text style={{ color: '#6B7280', textAlign: 'center', marginBottom: 20 }}>
              Solo marca como pagado si ya realizaste la transferencia. Falsos reportes pueden resultar en suspensión de tu cuenta.
            </Text>
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <TouchableOpacity
                style={{ backgroundColor: '#F3F4F6', paddingVertical: 12, paddingHorizontal: 20, borderRadius: 8, marginRight: 8 }}
                onPress={() => setShowConfirmPaidModal(false)}
              >
                <Text style={{ color: '#374151', fontWeight: '600' }}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={{ backgroundColor: colors.primary, paddingVertical: 12, paddingHorizontal: 20, borderRadius: 8 }}
                onPress={confirmMarkAsPaid}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>Sí, ya pagué</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    backgroundColor: '#fff',
  },
  backButton: {
    padding: 4,
    marginRight: 12,
  },
  headerCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
  },
  traderInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    position: 'relative',
  },
  avatarText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#6B7280',
  },
  onlineIndicator: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#10B981',
    borderWidth: 2,
    borderColor: '#fff',
  },
  traderDetails: {
    flex: 1,
  },
  traderNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  traderName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  verifiedIcon: {
    marginLeft: 4,
  },
  traderStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  statusIcon: {
    marginRight: 4,
  },
  statusText: {
    fontSize: 12,
    color: '#6B7280',
  },
  typingText: {
    fontSize: 12,
    color: '#10B981',
    fontStyle: 'italic',
    marginLeft: 8,
  },
  viewTradeButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  viewTradeButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  tradeStatusBanner: {
    backgroundColor: '#ECFDF5',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#D1FAE5',
  },
  tradeStatusHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tradeInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tradeIcon: {
    marginRight: 8,
  },
  tradeAmount: {
    fontSize: 14,
    color: '#065F46',
    fontWeight: '600',
  },
  tradeProgress: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  stepIndicator: {
    fontSize: 12,
    color: '#059669',
    marginRight: 8,
  },
  timerBadge: {
    backgroundColor: '#D1FAE5',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  timerText: {
    fontSize: 12,
    color: '#065F46',
    fontWeight: '600',
  },
  tradeStatusFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stepText: {
    fontSize: 12,
    color: '#065F46',
  },
  progressBar: {
    width: 96,
    height: 4,
    backgroundColor: '#D1FAE5',
    borderRadius: 2,
  },
  progressFill: {
    height: 4,
    backgroundColor: '#059669',
    borderRadius: 2,
  },
  quickActionsBanner: {
    backgroundColor: '#FEF3C7',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#FDE68A',
  },
  quickActionsContent: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  quickActionsInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  quickActionsIcon: {
    marginRight: 8,
  },
  quickActionsText: {
    fontSize: 14,
    color: '#92400E',
  },
  markAsPaidButton: {
    backgroundColor: '#2563EB',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  markAsPaidButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  paymentActionBanner: {
    backgroundColor: '#DBEAFE',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#93C5FD',
  },
  paymentActionContent: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  paymentActionInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  paymentActionIcon: {
    marginRight: 8,
  },
  paymentActionText: {
    fontSize: 14,
    color: '#1E40AF',
    fontWeight: '600',
  },
  securityNotice: {
    backgroundColor: '#FEF3C7',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#FDE68A',
  },
  securityContent: {
    flexDirection: 'row',
  },
  securityIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  securityTextContainer: {
    flex: 1,
  },
  securityTitle: {
    fontSize: 12,
    color: '#92400E',
    fontWeight: '600',
    marginBottom: 4,
  },
  securityText: {
    fontSize: 12,
    color: '#92400E',
    lineHeight: 16,
  },
  securityDismissButton: {
    backgroundColor: '#92400E',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 6,
    alignSelf: 'flex-end',
    marginTop: 12,
  },
  securityDismissButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  chatContainer: {
    flex: 1,
    backgroundColor: '#fff',
  },
  messagesContainer: {
    flex: 1,
  },
  messagesScroll: {
    flex: 1,
  },
  messagesContent: {
    padding: 16,
    paddingTop: 8,
    paddingBottom: 8,
    flexGrow: 1,
    justifyContent: 'flex-end',
  },
  systemMessageContainer: {
    alignItems: 'center',
    marginVertical: 8,
  },
  systemMessage: {
    backgroundColor: '#DBEAFE',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
  },
  systemIcon: {
    marginRight: 4,
  },
  systemMessageText: {
    fontSize: 12,
    color: '#1E40AF',
  },
  paymentInfoContainer: {
    marginBottom: 12,
  },
  userPaymentInfoContainer: {
    alignItems: 'flex-end',
  },
  traderPaymentInfoContainer: {
    alignItems: 'flex-start',
  },
  paymentInfoBubble: {
    borderWidth: 1,
    borderColor: '#BBF7D0',
    padding: 16,
    borderRadius: 16,
    maxWidth: '80%',
  },
  paymentInfoHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  paymentIcon: {
    marginRight: 8,
  },
  paymentInfoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#166534',
  },
  paymentInfoText: {
    fontSize: 14,
    color: '#1F2937',
    fontFamily: 'monospace',
    lineHeight: 20,
  },
  paymentInfoTimestamp: {
    fontSize: 12,
    color: '#059669',
    marginTop: 8,
  },
  messageContainer: {
    marginBottom: 12,
  },
  userMessageContainer: {
    alignItems: 'flex-end',
  },
  traderMessageContainer: {
    alignItems: 'flex-start',
  },
  messageBubble: {
    maxWidth: '80%',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 16,
  },
  userMessageBubble: {
    backgroundColor: colors.primary,
    borderBottomRightRadius: 4,
  },
  traderMessageBubble: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderBottomLeftRadius: 4,
  },
  messageText: {
    fontSize: 14,
    lineHeight: 20,
  },
  userMessageText: {
    color: '#fff',
  },
  traderMessageText: {
    color: '#1F2937',
  },
  messageTimestamp: {
    fontSize: 12,
    marginTop: 4,
  },
  userMessageTimestamp: {
    color: '#D1FAE5',
  },
  traderMessageTimestamp: {
    color: '#6B7280',
  },
  inputContainer: {
    backgroundColor: '#fff',
    padding: 16,
    paddingBottom: 16,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: -2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 8,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
  },
  inputWrapper: {
    flex: 1,
    marginRight: 8,
    backgroundColor: '#F9FAFB',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  textInput: {
    fontSize: 16,
    color: '#1F2937',
    maxHeight: 100,
    textAlignVertical: 'top',
    minHeight: 40,
    paddingHorizontal: 0,
    paddingVertical: Platform.OS === 'android' ? 8 : 12,
  },
  sendButton: {
    backgroundColor: colors.primary,
    width: 44,
    height: 44,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: '#E5E7EB',
  },
  userPaymentInfoBubble: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
    borderBottomRightRadius: 4,
  },
  traderPaymentInfoBubble: {
    backgroundColor: '#F0FDF4',
    borderColor: '#BBF7D0',
    borderBottomLeftRadius: 4,
  },
  userPaymentInfoTitle: {
    color: '#ffffff',
  },
  userPaymentInfoText: {
    color: '#ffffff',
  },
  userPaymentInfoTimestamp: {
    color: '#ffffff',
  },
  abandonButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#EF4444',
    marginLeft: 12,
  },
  abandonButtonText: {
    color: '#EF4444',
    fontSize: 14,
    fontWeight: '600',
  },
}); 