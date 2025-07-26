import React, { useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  PanResponder,
  Animated,
  Vibration,
  Platform,
} from 'react-native';

interface AlphabetIndexProps {
  letters: string[];
  onLetterPress: (letter: string) => void;
}

export const AlphabetIndex: React.FC<AlphabetIndexProps> = ({
  letters,
  onLetterPress,
}) => {
  const [selectedLetter, setSelectedLetter] = useState<string | null>(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(0.8)).current;

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      
      onPanResponderGrant: (evt) => {
        // Show the index
        Animated.parallel([
          Animated.timing(fadeAnim, {
            toValue: 1,
            duration: 200,
            useNativeDriver: true,
          }),
          Animated.spring(scaleAnim, {
            toValue: 1,
            friction: 5,
            useNativeDriver: true,
          }),
        ]).start();
        
        handleTouch(evt.nativeEvent.locationY);
      },
      
      onPanResponderMove: (evt) => {
        handleTouch(evt.nativeEvent.locationY);
      },
      
      onPanResponderRelease: () => {
        // Hide the index
        Animated.parallel([
          Animated.timing(fadeAnim, {
            toValue: 0,
            duration: 200,
            useNativeDriver: true,
          }),
          Animated.spring(scaleAnim, {
            toValue: 0.8,
            friction: 5,
            useNativeDriver: true,
          }),
        ]).start();
        
        setSelectedLetter(null);
      },
    })
  ).current;

  const handleTouch = (y: number) => {
    const letterHeight = 20; // Approximate height per letter
    const index = Math.floor(y / letterHeight);
    const clampedIndex = Math.max(0, Math.min(index, letters.length - 1));
    const letter = letters[clampedIndex];
    
    if (letter && letter !== selectedLetter) {
      setSelectedLetter(letter);
      onLetterPress(letter);
      
      // Haptic feedback
      if (Platform.OS === 'ios') {
        Vibration.vibrate(10);
      }
    }
  };

  return (
    <>
      {/* Letter preview bubble */}
      {selectedLetter && (
        <Animated.View
          style={[
            styles.letterPreview,
            {
              opacity: fadeAnim,
              transform: [{ scale: scaleAnim }],
            },
          ]}
        >
          <Text style={styles.letterPreviewText}>{selectedLetter}</Text>
        </Animated.View>
      )}

      {/* Alphabet index */}
      <View style={styles.container} {...panResponder.panHandlers}>
        {letters.map((letter) => (
          <View key={letter} style={styles.letterContainer}>
            <Text
              style={[
                styles.letter,
                selectedLetter === letter && styles.letterSelected,
              ]}
            >
              {letter}
            </Text>
          </View>
        ))}
      </View>
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    right: 0,
    top: '20%',
    bottom: '20%',
    width: 30,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 10,
  },
  letterContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 20,
  },
  letter: {
    fontSize: 11,
    fontWeight: '600',
    color: '#9CA3AF',
  },
  letterSelected: {
    color: '#34D399',
    transform: [{ scale: 1.2 }],
  },
  letterPreview: {
    position: 'absolute',
    right: 40,
    top: '50%',
    marginTop: -40,
    width: 80,
    height: 80,
    backgroundColor: '#34D399',
    borderRadius: 40,
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
  letterPreviewText: {
    fontSize: 36,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
});