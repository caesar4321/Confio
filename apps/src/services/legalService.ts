import { gql } from '@apollo/client';
import { client } from '../apollo/client';

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

export interface LegalDocument {
  title: string;
  content: string;
  version: string;
  lastUpdated: string;
  language: string;
}

export class LegalService {
  private static instance: LegalService;
  private cache: Map<string, LegalDocument> = new Map();

  private constructor() {}

  static getInstance(): LegalService {
    if (!LegalService.instance) {
      LegalService.instance = new LegalService();
    }
    return LegalService.instance;
  }

  async getLegalDocument(docType: 'terms' | 'privacy' | 'deletion', language?: string): Promise<LegalDocument> {
    const cacheKey = `${docType}-${language || 'default'}`;
    
    // Check cache first
    const cachedDoc = this.cache.get(cacheKey);
    if (cachedDoc) {
      return cachedDoc;
    }

    try {
      const { data } = await client.query({
        query: GET_LEGAL_DOCUMENT,
        variables: { docType, language },
        fetchPolicy: 'network-only', // Don't use Apollo cache, we'll handle caching ourselves
      });

      if (!data.legalDocument) {
        throw new Error(`Legal document of type ${docType} not found`);
      }

      // Cache the result
      this.cache.set(cacheKey, data.legalDocument);

      return data.legalDocument;
    } catch (error) {
      console.error('Error fetching legal document:', error);
      throw error;
    }
  }

  clearCache() {
    this.cache.clear();
  }
}

export const legalService = LegalService.getInstance(); 