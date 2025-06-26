import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  SafeAreaView,
  StatusBar,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';

type TraderRatingRouteProp = RouteProp<MainStackParamList, 'TraderRating'>;

const positiveTags = [
  'Respuesta rápida',
  'Muy confiable',
  'Proceso fluido',
  'Excelente comunicación',
  'Pago confirmado rápido',
  'Muy profesional',
  'Datos correctos',
  'Recomendado',
];

const negativeTags = [
  'Respuesta lenta',
  'Datos incorrectos',
  'Comunicación confusa',
  'Proceso complicado',
  'Tardó en confirmar',
  'Poco profesional',
];

const getRatingText = (rating: number) => {
  const texts: { [key: number]: string } = {
    1: 'Muy malo',
    2: 'Malo',
    3: 'Regular',
    4: 'Bueno',
    5: 'Excelente',
  };
  return texts[rating] || '';
};

const StarRating = ({ rating, onRatingChange, size = 'medium' }: { rating: number; onRatingChange: (n: number) => void; size?: 'medium' | 'large' }) => {
  const iconSize = size === 'large' ? 32 : 24;
  return (
    <View style={{ flexDirection: 'row' }}>
      {[1, 2, 3, 4, 5].map((star) => (
        <TouchableOpacity
          key={star}
          onPress={() => onRatingChange(star)}
          style={{ marginHorizontal: 2 }}
        >
          <Icon
            name="star"
            size={iconSize}
            color={star <= rating ? '#FBBF24' : '#D1D5DB'}
          />
        </TouchableOpacity>
      ))}
    </View>
  );
};

export const TraderRatingScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute<any>();
  // Fallback mock data for demo/testing
  const trader = route.params?.trader || {
    name: 'Maria L.',
    verified: true,
    completedTrades: 248,
    successRate: 99.2,
  };
  const tradeDetails = route.params?.tradeDetails || {
    amount: '100.00',
    crypto: 'cUSD',
    totalPaid: '3,610.00',
    method: 'Banco Venezuela',
    date: '21 Jun 2025, 14:45',
    duration: '8 minutos',
  };

  const [overallRating, setOverallRating] = useState(0);
  const [communicationRating, setCommunicationRating] = useState(0);
  const [speedRating, setSpeedRating] = useState(0);
  const [reliabilityRating, setReliabilityRating] = useState(0);
  const [comment, setComment] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleTagToggle = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const handleSubmitRating = () => {
    if (overallRating === 0) {
      Alert.alert('Por favor selecciona una calificación general');
      return;
    }
    // Here you would send the rating to the backend
    setIsSubmitted(true);
  };

  const handleGoBack = () => {
    navigation.goBack();
  };

  if (isSubmitted) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="dark-content" backgroundColor="#fff" />
        <View style={styles.headerRow}>
          <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#374151" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Calificación Enviada</Text>
        </View>
        <View style={styles.centeredContent}>
          <View style={styles.successCard}>
            <View style={styles.successIcon}>
              <Icon name="check" size={32} color="#fff" />
            </View>
            <Text style={styles.successTitle}>¡Gracias por tu calificación!</Text>
            <Text style={styles.successText}>
              Tu opinión ayuda a mejorar la experiencia de todos los usuarios en la plataforma.
            </Text>
            <View style={styles.summaryCard}>
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Calificaste a {trader.name}:</Text>
                <View style={{ flexDirection: 'row', marginLeft: 8 }}>
                  {[1, 2, 3, 4, 5].map((star) => (
                    <Icon
                      key={star}
                      name="star"
                      size={20}
                      color={star <= overallRating ? '#FBBF24' : '#D1D5DB'}
                    />
                  ))}
                </View>
              </View>
              <Text style={styles.ratingText}>{getRatingText(overallRating)}</Text>
            </View>
            <TouchableOpacity style={styles.primaryButton} onPress={handleGoBack}>
              <Text style={styles.primaryButtonText}>Continuar Intercambiando</Text>
            </TouchableOpacity>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#374151" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Calificar Intercambio</Text>
      </View>
      <ScrollView style={styles.content} contentContainerStyle={{ paddingBottom: 32 }}>
        {/* Trader Info */}
        <View style={styles.traderCard}>
          <View style={styles.traderRow}>
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{trader.name.charAt(0)}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 2 }}>
                <Text style={styles.traderName}>{trader.name}</Text>
                {trader.verified && (
                  <Icon name="shield" size={16} color={colors.accent} style={{ marginLeft: 4 }} />
                )}
              </View>
              <Text style={styles.traderStats}>{trader.completedTrades} operaciones • {trader.successRate}% éxito</Text>
            </View>
          </View>
          <View style={styles.tradeSummaryCard}>
            <Text style={styles.tradeSummaryTitle}>Resumen del intercambio</Text>
            <View style={styles.tradeSummaryRow}><Text style={styles.tradeSummaryLabel}>Cantidad:</Text><Text>{tradeDetails.amount} {tradeDetails.crypto}</Text></View>
            <View style={styles.tradeSummaryRow}><Text style={styles.tradeSummaryLabel}>Total pagado:</Text><Text>{tradeDetails.totalPaid} Bs.</Text></View>
            <View style={styles.tradeSummaryRow}><Text style={styles.tradeSummaryLabel}>Método:</Text><Text>{tradeDetails.method}</Text></View>
            <View style={styles.tradeSummaryRow}><Text style={styles.tradeSummaryLabel}>Duración:</Text><Text style={{ color: colors.success }}>{tradeDetails.duration}</Text></View>
          </View>
        </View>
        {/* Overall Rating */}
        <View style={styles.ratingCard}>
          <Text style={styles.ratingTitle}>Calificación general</Text>
          <View style={{ alignItems: 'center', marginVertical: 8 }}>
            <StarRating rating={overallRating} onRatingChange={setOverallRating} size="large" />
            {overallRating > 0 && (
              <Text style={styles.ratingText}>{getRatingText(overallRating)}</Text>
            )}
          </View>
        </View>
        {/* Detailed Ratings */}
        <View style={styles.ratingCard}>
          <Text style={styles.ratingTitle}>Calificaciones específicas</Text>
          <View style={{ marginTop: 8 }}>
            <View style={styles.detailRatingRow}>
              <View style={styles.detailRatingLabel}><Icon name="message-circle" size={18} color={colors.accent} style={{ marginRight: 6 }} /><Text style={styles.detailRatingText}>Comunicación</Text></View>
              <StarRating rating={communicationRating} onRatingChange={setCommunicationRating} />
            </View>
            <View style={styles.detailRatingRow}>
              <View style={styles.detailRatingLabel}><Icon name="clock" size={18} color={colors.success} style={{ marginRight: 6 }} /><Text style={styles.detailRatingText}>Velocidad</Text></View>
              <StarRating rating={speedRating} onRatingChange={setSpeedRating} />
            </View>
            <View style={styles.detailRatingRow}>
              <View style={styles.detailRatingLabel}><Icon name="shield" size={18} color={colors.secondary} style={{ marginRight: 6 }} /><Text style={styles.detailRatingText}>Confiabilidad</Text></View>
              <StarRating rating={reliabilityRating} onRatingChange={setReliabilityRating} />
            </View>
          </View>
        </View>
        {/* Quick Tags */}
        <View style={styles.ratingCard}>
          <Text style={styles.ratingTitle}>Etiquetas rápidas</Text>
          {overallRating >= 4 && (
            <View style={{ marginBottom: 8 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 4 }}>
                <Icon name="thumbs-up" size={16} color={colors.success} style={{ marginRight: 4 }} />
                <Text style={{ color: colors.success, fontWeight: '600' }}>Aspectos positivos</Text>
              </View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {positiveTags.map((tag) => (
                  <TouchableOpacity
                    key={tag}
                    onPress={() => handleTagToggle(tag)}
                    style={[
                      styles.tagButton,
                      selectedTags.includes(tag)
                        ? styles.tagButtonSelectedPositive
                        : styles.tagButtonPositive,
                    ]}
                  >
                    <Text style={selectedTags.includes(tag) ? styles.tagTextSelected : styles.tagText}>{tag}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          )}
          {overallRating > 0 && overallRating <= 3 && (
            <View>
              <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 4 }}>
                <Icon name="thumbs-down" size={16} color="#EF4444" style={{ marginRight: 4 }} />
                <Text style={{ color: '#EF4444', fontWeight: '600' }}>Aspectos a mejorar</Text>
              </View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {negativeTags.map((tag) => (
                  <TouchableOpacity
                    key={tag}
                    onPress={() => handleTagToggle(tag)}
                    style={[
                      styles.tagButton,
                      selectedTags.includes(tag)
                        ? styles.tagButtonSelectedNegative
                        : styles.tagButtonNegative,
                    ]}
                  >
                    <Text style={selectedTags.includes(tag) ? styles.tagTextSelected : styles.tagText}>{tag}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          )}
        </View>
        {/* Comment */}
        <View style={styles.ratingCard}>
          <Text style={styles.ratingTitle}>Comentario (opcional)</Text>
          <TextInput
            value={comment}
            onChangeText={setComment}
            placeholder="Comparte tu experiencia con otros usuarios..."
            style={styles.commentInput}
            multiline
            maxLength={500}
            numberOfLines={4}
          />
          <View style={styles.commentFooter}>
            <Text style={styles.commentCount}>{comment.length}/500 caracteres</Text>
            {comment.length > 0 && (
              <Text style={styles.commentPublic}>Tu comentario será público</Text>
            )}
          </View>
        </View>
        {/* Warning */}
        <View style={styles.warningCard}>
          <Icon name="alert-triangle" size={16} color="#D97706" style={{ marginRight: 8 }} />
          <View style={{ flex: 1 }}>
            <Text style={styles.warningTitle}>Calificación justa</Text>
            <Text style={styles.warningText}>Las calificaciones afectan la reputación del comerciante. Por favor sé justo y honesto en tu evaluación.</Text>
          </View>
        </View>
      </ScrollView>
      <View style={styles.submitBar}>
        <TouchableOpacity
          style={[styles.primaryButton, overallRating === 0 && styles.primaryButtonDisabled]}
          onPress={handleSubmitRating}
          disabled={overallRating === 0}
        >
          <Text style={styles.primaryButtonText}>Enviar Calificación</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F9FAFB' },
  headerRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8, backgroundColor: '#fff' },
  backButton: { padding: 4, marginRight: 12 },
  headerTitle: { fontSize: 20, fontWeight: 'bold', color: '#1F2937' },
  content: { flex: 1 },
  traderCard: { backgroundColor: '#fff', borderRadius: 12, padding: 16, marginBottom: 16 },
  traderRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: '#E5E7EB', justifyContent: 'center', alignItems: 'center', marginRight: 12 },
  avatarText: { fontSize: 22, fontWeight: 'bold', color: '#4B5563' },
  traderName: { fontSize: 18, fontWeight: 'bold', marginRight: 4 },
  traderStats: { fontSize: 13, color: '#6B7280' },
  tradeSummaryCard: { backgroundColor: '#F9FAFB', borderRadius: 8, padding: 12, marginTop: 4 },
  tradeSummaryTitle: { fontWeight: '600', marginBottom: 4, color: '#1F2937' },
  tradeSummaryRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 2 },
  tradeSummaryLabel: { color: '#6B7280', fontSize: 13 },
  ratingCard: { backgroundColor: '#fff', borderRadius: 12, padding: 16, marginBottom: 16 },
  ratingTitle: { fontWeight: 'bold', fontSize: 16, marginBottom: 8, color: '#1F2937' },
  ratingText: { fontSize: 16, fontWeight: '600', color: '#FBBF24', textAlign: 'center', marginTop: 4 },
  detailRatingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  detailRatingLabel: { flexDirection: 'row', alignItems: 'center' },
  detailRatingText: { fontSize: 15, fontWeight: '500', color: '#374151' },
  tagButton: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16, marginBottom: 6 },
  tagButtonPositive: { backgroundColor: '#D1FAE5' },
  tagButtonSelectedPositive: { backgroundColor: colors.success },
  tagButtonNegative: { backgroundColor: '#FECACA' },
  tagButtonSelectedNegative: { backgroundColor: '#EF4444' },
  tagText: { fontSize: 13, color: '#374151' },
  tagTextSelected: { fontSize: 13, color: '#fff' },
  commentInput: { backgroundColor: '#F3F4F6', borderRadius: 8, padding: 12, fontSize: 15, minHeight: 80, textAlignVertical: 'top', marginTop: 8 },
  commentFooter: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 },
  commentCount: { fontSize: 12, color: '#6B7280' },
  commentPublic: { fontSize: 12, color: colors.success },
  warningCard: { flexDirection: 'row', alignItems: 'flex-start', backgroundColor: '#FEF3C7', borderRadius: 8, padding: 12, marginBottom: 16 },
  warningTitle: { fontWeight: '600', color: '#92400E', marginBottom: 2 },
  warningText: { fontSize: 13, color: '#B45309' },
  submitBar: { backgroundColor: '#fff', padding: 16, borderTopWidth: 1, borderTopColor: '#E5E7EB' },
  primaryButton: {
    backgroundColor: colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    alignItems: 'center',
    minHeight: 48,
    marginBottom: 0,
  },
  primaryButtonDisabled: { backgroundColor: '#E5E7EB' },
  primaryButtonText: { color: '#fff', fontSize: 17, fontWeight: 'bold' },
  centeredContent: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 16 },
  successCard: { backgroundColor: '#fff', borderRadius: 16, padding: 24, alignItems: 'center', width: '100%', maxWidth: 340 },
  successIcon: { width: 64, height: 64, backgroundColor: colors.success, borderRadius: 32, justifyContent: 'center', alignItems: 'center', marginBottom: 16 },
  successTitle: { fontSize: 20, fontWeight: 'bold', color: '#1F2937', marginBottom: 8, textAlign: 'center' },
  successText: { fontSize: 15, color: '#6B7280', marginBottom: 12, textAlign: 'center' },
  summaryCard: { backgroundColor: '#F9FAFB', borderRadius: 8, padding: 12, marginBottom: 8, width: '100%' },
  summaryRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 2 },
  summaryLabel: { fontWeight: '600', color: '#1F2937', marginRight: 4 },
}); 