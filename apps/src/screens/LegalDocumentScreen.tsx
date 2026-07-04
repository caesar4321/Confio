import React from 'react';
import { View, Text, ScrollView, StyleSheet, Linking, TouchableOpacity } from 'react-native';
import { useQuery } from '@apollo/client';
import gql from 'graphql-tag';
import { useRoute, useNavigation, NavigationProp } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { SkeletonLoader } from '../components/SkeletonLoader';
import { EmptyState } from '../components/EmptyState';
import { colors } from '../config/theme';

const GET_LEGAL_DOCUMENT = gql`
  query GetLegalDocument($docType: String!, $language: String) {
    legalDocument(docType: $docType, language: $language) {
      title
      content
      version
      lastUpdated
      language
    }
  }
`;

type RouteParams = {
  docType: 'terms' | 'privacy' | 'deletion';
};

type LegalSection = {
  title: string;
  content: string | string[] | Record<string, any>;
};

type ContentType = string | string[] | Record<string, any>;

// Shown in the header before the server title arrives (and as fallback).
const FALLBACK_TITLES: Record<RouteParams['docType'], string> = {
  terms: 'Términos de Servicio',
  privacy: 'Política de Privacidad',
  deletion: 'Eliminación de Datos',
};

const LegalDocumentScreen = () => {
  const route = useRoute();
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const { docType } = route.params as RouteParams;

  const { loading, error, data, refetch } = useQuery(GET_LEGAL_DOCUMENT, {
    variables: { docType, language: 'es' },
  });

  const handleTelegramPress = async () => {
    const telegramUrl = 'tg://resolve?domain=confio4world';
    const webUrl = 'https://t.me/confio4world';
    try {
      const canOpen = await Linking.canOpenURL(telegramUrl);
      if (canOpen) {
        await Linking.openURL(telegramUrl);
      } else {
        // Fallback to t.me URL
        await Linking.openURL(webUrl);
      }
    } catch (error) {
      // Fallback to t.me URL
      await Linking.openURL(webUrl);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <Header
          title={FALLBACK_TITLES[docType]}
          navigation={navigation}
          backgroundColor={colors.background}
          isLight={false}
        />
        <View style={styles.content}>
          <SkeletonLoader width={180} height={12} style={{ marginBottom: 28 }} />
          {[0, 1, 2].map((i) => (
            <View key={i} style={{ marginBottom: 32 }}>
              <SkeletonLoader width="55%" height={18} style={{ marginBottom: 14 }} />
              <SkeletonLoader height={13} style={{ marginBottom: 9 }} />
              <SkeletonLoader height={13} style={{ marginBottom: 9 }} />
              <SkeletonLoader width="82%" height={13} />
            </View>
          ))}
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.container}>
        <Header
          title={FALLBACK_TITLES[docType]}
          navigation={navigation}
          backgroundColor={colors.background}
          isLight={false}
        />
        <EmptyState
          icon="file-text"
          title="No pudimos cargar el documento"
          subtitle="Revisa tu conexión e intenta de nuevo."
          actionLabel="Reintentar"
          onAction={() => refetch()}
        />
      </View>
    );
  }

  const { title, content, version, lastUpdated } = data.legalDocument;

  const renderContent = (content: ContentType) => {
    if (typeof content === 'string') {
      if (content.includes('t.me/FansDeJulian') || content.includes('t.me/confio4world')) {
        return (
          <TouchableOpacity onPress={handleTelegramPress} accessibilityRole="link" accessibilityLabel="Abrir canal de Telegram de Confío">
            <Text style={[styles.paragraph, styles.link]}>t.me/confio4world</Text>
          </TouchableOpacity>
        );
      }
      return <Text style={styles.paragraph}>{content}</Text>;
    }
    if (Array.isArray(content)) {
      // Check if this is a definitions array (array of objects with term and definition)
      if (content.length > 0 && typeof content[0] === 'object' && 'term' in content[0] && 'definition' in content[0]) {
        return (
          <View style={styles.definitionsContainer}>
            {content.map((item: any, index: number) => (
              <View key={index} style={styles.definitionItem}>
                <Text style={styles.termText}>{item.term}</Text>
                <Text style={styles.definitionText}>{item.definition}</Text>
              </View>
            ))}
          </View>
        );
      }
      // Regular list rendering
      return (
        <View style={styles.listContainer}>
          {content.map((item, index) => (
            <View key={index} style={styles.listItem}>
              <Text style={styles.bulletPoint}>•</Text>
              <Text style={styles.listItemText}>
                {typeof item === 'string' ? item : renderContent(item)}
              </Text>
            </View>
          ))}
        </View>
      );
    }
    if (typeof content === 'object') {
      return (
        <View>
          {Object.entries(content).map(([key, value]) => (
            <View key={key} style={styles.contentSection}>
              <Text style={styles.subheading}>
                {key.replace(/_/g, ' ').toUpperCase()}
              </Text>
              {key === 'telegram' ? (
                <TouchableOpacity onPress={handleTelegramPress} accessibilityRole="link" accessibilityLabel="Abrir canal de Telegram de Confío">
                  <Text style={[styles.paragraph, styles.link]}>t.me/confio4world</Text>
                </TouchableOpacity>
              ) : (
                renderContent(value)
              )}
            </View>
          ))}
        </View>
      );
    }
    return null;
  };

  // Parse the JSON strings in the content array
  const parsedSections = content.map((section: string) => JSON.parse(section) as LegalSection);

  const updatedAt = new Date(lastUpdated).toLocaleDateString('es-ES', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });

  return (
    <View style={styles.container}>
      <Header
        title={title || FALLBACK_TITLES[docType]}
        navigation={navigation}
        backgroundColor={colors.background}
        isLight={false}
      />
      <ScrollView style={styles.scrollView} contentContainerStyle={styles.content}>
        <Text style={styles.meta}>
          Versión {version} · Actualizado el {updatedAt}
        </Text>
        {parsedSections.map((section: LegalSection, index: number) => (
          <View key={index} style={styles.section}>
            <Text style={styles.sectionTitle} accessibilityRole="header">{section.title}</Text>
            {renderContent(section.content)}
          </View>
        ))}
      </ScrollView>
    </View>
  );
};

// Legal text reads as a clean typographic document: white page, clear
// hierarchy, no boxed sections. The only color is the brand accent on
// bullets, links, and the definition rule.
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollView: {
    flex: 1,
  },
  content: {
    paddingHorizontal: 24,
    paddingTop: 20,
    paddingBottom: 48,
  },
  meta: {
    fontSize: 13,
    color: colors.text.secondary,
    marginBottom: 28,
  },
  section: {
    marginBottom: 32,
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 10,
    lineHeight: 24,
  },
  subheading: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
    color: colors.text.secondary,
    marginBottom: 6,
  },
  paragraph: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.gray700,
    marginBottom: 10,
  },
  listContainer: {
    marginBottom: 6,
  },
  listItem: {
    flexDirection: 'row',
    marginBottom: 8,
  },
  bulletPoint: {
    fontSize: 15,
    lineHeight: 24,
    marginRight: 10,
    color: colors.primary,
  },
  listItemText: {
    flex: 1,
    fontSize: 15,
    lineHeight: 24,
    color: colors.gray700,
  },
  contentSection: {
    marginBottom: 18,
  },
  link: {
    color: colors.primaryDark,
    textDecorationLine: 'underline',
  },
  definitionsContainer: {
    marginBottom: 6,
  },
  definitionItem: {
    marginBottom: 14,
  },
  termText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 4,
  },
  definitionText: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.gray700,
    paddingLeft: 12,
    borderLeftWidth: 2,
    borderLeftColor: colors.primaryLight,
  },
});

export default LegalDocumentScreen;
