import React from 'react';
import { View, Text, StyleSheet, Linking, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

export const DiscoverScreen = () => {

  // Two primary tutorials
  const TUTORIALS: Array<{ key: string; title: string; description: string; icon: any; url: string }> = [
    {
      key: 'general',
      title: 'Tutorial general de Confío',
      description: 'Guía rápida para empezar a usar la app.',
      icon: 'play-circle',
      url: 'https://youtu.be/WCpoBZzgMyY?si=fHoDD7updJz_3yo4',
    },
    {
      key: 'earn',
      title: 'Cómo ganar con Confío',
      description: 'Aprende a aprovechar Confío para generar ingresos.',
      icon: 'trending-up',
      url: 'https://youtu.be/LY-H_N9FVDo',
    },
  ];

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <Icon name="compass" size={48} color="#8B5CF6" style={{ marginRight: 12 }} />
        <View>
          <Text style={styles.title}>Descubrir</Text>
          <Text style={styles.subtitle}>Aprende a usar Confío paso a paso.</Text>
        </View>
      </View>

      <View style={styles.grid}>
        {TUTORIALS.map((item: any) => (
          <TouchableOpacity key={item.key} style={styles.card} onPress={() => Linking.openURL(item.url)} activeOpacity={0.85}>
            <View style={styles.cardIconWrap}>
              <Icon name={item.icon} size={22} color="#8B5CF6" />
            </View>
            <View style={styles.cardTextWrap}>
              <Text style={styles.cardTitle}>{item.title}</Text>
              <Text style={styles.cardDesc}>{item.description}</Text>
            </View>
            <Icon name="chevron-right" size={20} color="#9CA3AF" />
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity style={styles.footerCta} onPress={() => Linking.openURL('https://confio.lat')}>
        <Text style={styles.footerCtaText}>Más en confio.lat</Text>
        <Icon name="external-link" size={16} color="#8B5CF6" />
      </TouchableOpacity>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#FFFFFF' },
  content: { padding: 16, paddingBottom: 32 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 2,
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    marginBottom: 16,
  },
  grid: { marginTop: 8 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F9FAFB',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  cardIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 8,
    backgroundColor: '#EEF2FF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  cardTextWrap: { flex: 1 },
  cardTitle: { fontSize: 16, fontWeight: '700', color: '#111827' },
  cardDesc: { fontSize: 13, color: '#6B7280', marginTop: 2 },
  footerCta: {
    alignSelf: 'center',
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  footerCtaText: { color: '#8B5CF6', fontWeight: '600', marginRight: 6 },
});

export default DiscoverScreen;
