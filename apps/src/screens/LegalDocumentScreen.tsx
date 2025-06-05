import React from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator } from 'react-native';
import { useQuery } from '@apollo/client';
import gql from 'graphql-tag';
import { useRoute } from '@react-navigation/native';

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

const LegalDocumentScreen = () => {
  const route = useRoute();
  const { docType } = route.params as RouteParams;

  const { loading, error, data } = useQuery(GET_LEGAL_DOCUMENT, {
    variables: { docType, language: 'es' },
  });

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

  const renderContent = (content: any) => {
    if (typeof content === 'string') {
      return <Text style={styles.paragraph}>{content}</Text>;
    }
    if (Array.isArray(content)) {
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
              {renderContent(value)}
            </View>
          ))}
        </View>
      );
    }
    return null;
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>{title}</Text>
        <View style={styles.metaContainer}>
          <Text style={styles.metaText}>Versión: {version}</Text>
          <Text style={styles.metaText}>
            Última actualización: {new Date(lastUpdated).toLocaleDateString('es-ES')}
          </Text>
          <View style={styles.legallyBindingNotice}>
            <Text style={styles.legallyBindingText}>
              ⚠️ Este es el documento legalmente vinculante en español.
            </Text>
          </View>
        </View>
      </View>
      <View style={styles.content}>
        {content.map((section: any, index: number) => (
          <View key={index} style={styles.section}>
            <Text style={styles.sectionTitle}>{section.title}</Text>
            {renderContent(section.content)}
          </View>
        ))}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
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
  header: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1a1a1a',
    marginBottom: 10,
  },
  metaContainer: {
    marginTop: 10,
  },
  metaText: {
    fontSize: 14,
    color: '#666',
    marginBottom: 5,
  },
  legallyBindingNotice: {
    marginTop: 10,
    padding: 10,
    backgroundColor: '#fff3cd',
    borderWidth: 1,
    borderColor: '#ffeeba',
    borderRadius: 4,
  },
  legallyBindingText: {
    color: '#856404',
    fontWeight: '500',
  },
  content: {
    padding: 20,
  },
  section: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#2c3e50',
    marginBottom: 10,
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
    color: '#333',
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
});

export default LegalDocumentScreen; 