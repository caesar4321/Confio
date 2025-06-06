import React from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator, Linking, TouchableOpacity } from 'react-native';
import { useQuery } from '@apollo/client';
import gql from 'graphql-tag';
import { useRoute, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';

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

const LegalDocumentScreen = () => {
  const route = useRoute();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { docType } = route.params as RouteParams;

  const { loading, error, data } = useQuery(GET_LEGAL_DOCUMENT, {
    variables: { docType, language: 'es' },
  });

  const handleTelegramPress = async () => {
    const telegramUrl = 'https://t.me/FansDeJulian/13765';
    const canOpen = await Linking.canOpenURL(telegramUrl);
    if (canOpen) {
      await Linking.openURL(telegramUrl);
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#007AFF" />
        <Text style={styles.loadingText}>Cargando...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.errorContainer}>
        <Text style={styles.errorText}>Error: {error.message}</Text>
      </View>
    );
  }

  const { title, content, version, lastUpdated, language } = data.legalDocument;

  const renderContent = (content: ContentType) => {
    if (typeof content === 'string') {
      if (content.includes('t.me/FansDeJulian')) {
        return (
          <TouchableOpacity onPress={handleTelegramPress}>
            <Text style={[styles.paragraph, styles.link]}>t.me/FansDeJulian</Text>
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
                <Text style={styles.termText}>{item.term}:</Text>
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
              <Text style={styles.sectionTitle}>
                {key.replace(/_/g, ' ').toUpperCase()}
              </Text>
              {key === 'telegram' ? (
                <TouchableOpacity onPress={handleTelegramPress}>
                  <Text style={[styles.paragraph, styles.link]}>{value}</Text>
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

  return (
    <View style={styles.container}>
      <Header 
        title={title}
        navigation={navigation}
        backgroundColor="#fff"
        isLight={false}
      />
      <ScrollView style={styles.scrollView}>
        <View style={styles.metaContainer}>
          <Text style={styles.metaText}>Versión: {version}</Text>
          <Text style={styles.metaText}>
            Última actualización: {new Date(lastUpdated).toLocaleDateString('es-ES')}
          </Text>
        </View>
        <View style={styles.content}>
          {parsedSections.map((section: LegalSection, index: number) => (
            <View key={index} style={styles.section}>
              <Text style={styles.sectionTitle}>{section.title}</Text>
              {renderContent(section.content)}
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  scrollView: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 10,
    fontSize: 16,
    color: '#666',
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    color: '#dc3545',
    fontSize: 16,
    textAlign: 'center',
  },
  metaContainer: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  metaText: {
    fontSize: 14,
    color: '#666',
    marginBottom: 5,
  },
  content: {
    padding: 20,
  },
  section: {
    marginBottom: 20,
    padding: 15,
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#2c3e50',
    marginBottom: 10,
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: '#72D9BC',
  },
  paragraph: {
    fontSize: 16,
    lineHeight: 24,
    color: '#333',
    marginBottom: 10,
  },
  listContainer: {
    marginVertical: 10,
  },
  listItem: {
    flexDirection: 'row',
    marginBottom: 8,
  },
  bulletPoint: {
    fontSize: 16,
    marginRight: 8,
    color: '#72D9BC',
  },
  listItemText: {
    flex: 1,
    fontSize: 16,
    lineHeight: 24,
    color: '#333',
  },
  contentSection: {
    marginVertical: 15,
  },
  link: {
    color: '#34d399',
    textDecorationLine: 'underline',
  },
  definitionsContainer: {
    marginVertical: 10,
  },
  definitionItem: {
    marginBottom: 12,
  },
  termText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#2c3e50',
    marginBottom: 4,
  },
  definitionText: {
    fontSize: 16,
    lineHeight: 24,
    color: '#333',
    paddingLeft: 8,
  },
});

export default LegalDocumentScreen; 