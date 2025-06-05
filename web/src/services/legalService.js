import { gql } from '@apollo/client';
import client from '../apollo/client';

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

export const getLegalDocument = async (docType, language = 'es') => {
  try {
    const { data } = await client.query({
      query: GET_LEGAL_DOCUMENT,
      variables: { docType, language },
    });
    return data.legalDocument;
  } catch (error) {
    console.error('Error fetching legal document:', error);
    throw error;
  }
}; 