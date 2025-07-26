import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Animated,
  Platform,
  Dimensions,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';

interface FloatingActionButtonProps {
  onSendPress: () => void;
  onReceivePress: () => void;
  onScanPress: () => void;
}

export const FloatingActionButton: React.FC<FloatingActionButtonProps> = ({
  onSendPress,
  onReceivePress,
  onScanPress,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const rotateAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(1)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const translateYSend = useRef(new Animated.Value(0)).current;
  const translateYReceive = useRef(new Animated.Value(0)).current;
  const translateYScan = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (isExpanded) {
      // Expand animations
      Animated.parallel([
        Animated.spring(rotateAnim, {
          toValue: 1,
          useNativeDriver: true,
        }),
        Animated.spring(scaleAnim, {
          toValue: 0.9,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.spring(translateYSend, {
          toValue: -180,
          tension: 65,
          friction: 7,
          useNativeDriver: true,
        }),
        Animated.spring(translateYReceive, {
          toValue: -120,
          tension: 65,
          friction: 7,
          delay: 50,
          useNativeDriver: true,
        }),
        Animated.spring(translateYScan, {
          toValue: -60,
          tension: 65,
          friction: 7,
          delay: 100,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      // Collapse animations
      Animated.parallel([
        Animated.spring(rotateAnim, {
          toValue: 0,
          useNativeDriver: true,
        }),
        Animated.spring(scaleAnim, {
          toValue: 1,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.spring(translateYSend, {
          toValue: 0,
          tension: 65,
          friction: 7,
          useNativeDriver: true,
        }),
        Animated.spring(translateYReceive, {
          toValue: 0,
          tension: 65,
          friction: 7,
          useNativeDriver: true,
        }),
        Animated.spring(translateYScan, {
          toValue: 0,
          tension: 65,
          friction: 7,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [isExpanded]);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  const handleAction = (action: () => void) => {
    setIsExpanded(false);
    setTimeout(action, 200);
  };

  const rotation = rotateAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '45deg'],
  });

  return (
    <>
      {/* Backdrop */}
      {isExpanded && (
        <TouchableOpacity
          style={styles.backdrop}
          activeOpacity={1}
          onPress={() => setIsExpanded(false)}
        >
          <Animated.View style={[styles.backdropView, { opacity: fadeAnim }]} />
        </TouchableOpacity>
      )}

      {/* FAB Container */}
      <View style={styles.container}>
        {/* Action Buttons */}
        <Animated.View
          style={[
            styles.actionButton,
            {
              opacity: fadeAnim,
              transform: [{ translateY: translateYSend }, { scale: fadeAnim }],
            },
          ]}
        >
          <TouchableOpacity
            style={styles.actionButtonTouch}
            onPress={() => handleAction(onSendPress)}
          >
            <View style={[styles.actionButtonInner, { backgroundColor: '#34D399' }]}>
              <Icon name="send" size={20} color="#fff" />
            </View>
            <Text style={styles.actionLabel}>Enviar</Text>
          </TouchableOpacity>
        </Animated.View>

        <Animated.View
          style={[
            styles.actionButton,
            {
              opacity: fadeAnim,
              transform: [{ translateY: translateYReceive }, { scale: fadeAnim }],
            },
          ]}
        >
          <TouchableOpacity
            style={styles.actionButtonTouch}
            onPress={() => handleAction(onReceivePress)}
          >
            <View style={[styles.actionButtonInner, { backgroundColor: '#3B82F6' }]}>
              <Icon name="download" size={20} color="#fff" />
            </View>
            <Text style={styles.actionLabel}>Recibir</Text>
          </TouchableOpacity>
        </Animated.View>

        <Animated.View
          style={[
            styles.actionButton,
            {
              opacity: fadeAnim,
              transform: [{ translateY: translateYScan }, { scale: fadeAnim }],
            },
          ]}
        >
          <TouchableOpacity
            style={styles.actionButtonTouch}
            onPress={() => handleAction(onScanPress)}
          >
            <View style={[styles.actionButtonInner, { backgroundColor: '#8B5CF6' }]}>
              <Icon name="camera" size={20} color="#fff" />
            </View>
            <Text style={styles.actionLabel}>Escanear</Text>
          </TouchableOpacity>
        </Animated.View>

        {/* Main FAB */}
        <TouchableOpacity onPress={toggleExpanded} activeOpacity={0.8}>
          <Animated.View style={{ transform: [{ scale: scaleAnim }] }}>
            <View style={styles.fab}>
              <Svg height="100%" width="100%" style={StyleSheet.absoluteFillObject}>
                <Defs>
                  <LinearGradient id="fabGrad" x1="0" y1="0" x2="1" y2="1">
                    <Stop offset="0" stopColor="#34D399" />
                    <Stop offset="1" stopColor="#10B981" />
                  </LinearGradient>
                </Defs>
                <Rect width="100%" height="100%" fill="url(#fabGrad)" rx="28" />
              </Svg>
              <Animated.View style={{ transform: [{ rotate: rotation }] }}>
                <Icon name="plus" size={28} color="#fff" />
              </Animated.View>
            </View>
          </Animated.View>
        </TouchableOpacity>
      </View>
    </>
  );
};

const { width } = Dimensions.get('window');

const styles = StyleSheet.create({
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 998,
  },
  backdropView: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  container: {
    position: 'absolute',
    bottom: 24,
    right: 16,
    alignItems: 'center',
    zIndex: 999,
  },
  fab: {
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3,
        shadowRadius: 8,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  actionButton: {
    position: 'absolute',
    alignItems: 'center',
  },
  actionButtonTouch: {
    alignItems: 'center',
  },
  actionButtonInner: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 4,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.2,
        shadowRadius: 4,
      },
      android: {
        elevation: 4,
      },
    }),
  },
  actionLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#1F2937',
    backgroundColor: '#FFFFFF',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.1,
        shadowRadius: 2,
      },
      android: {
        elevation: 2,
      },
    }),
  },
});