import React from 'react';
import { useQuery } from '@apollo/client';
import gql from 'graphql-tag';
import './LegalDocument.css';

const GET_LEGAL_DOCUMENT = gql`
  query GetLegalDocument($docType: String!) {
    legalDocument(docType: $docType) {
      title
      content
      version
      lastUpdated
      language
      isLegallyBinding
    }
  }
`;

const LegalDocument = ({ type }) => {
  const { loading, error, data } = useQuery(GET_LEGAL_DOCUMENT, {
    variables: { docType: type },
    fetchPolicy: 'network-only',  // Ensure we always get fresh data
    onError: (error) => {
      console.error('GraphQL Error:', error);
      // Log specific error details if available
      if (error.graphQLErrors?.[0]?.extensions?.code) {
        console.error('Error code:', error.graphQLErrors[0].extensions.code);
      }
      if (error.graphQLErrors?.[0]?.extensions?.params) {
        console.error('Error params:', error.graphQLErrors[0].extensions.params);
      }
    }
  });

  if (loading) return <div className="legal-document loading">Cargando...</div>;
  if (error) {
    console.error('GraphQL Error:', error);
    let errorMessage = 'Error al cargar el documento';
    
    // Handle specific error cases
    if (error.graphQLErrors?.[0]?.extensions?.code === 'INVALID_DOCUMENT_TYPE') {
      errorMessage = 'Tipo de documento no válido';
    } else if (error.graphQLErrors?.[0]?.extensions?.code === 'DOCUMENT_TYPE_REQUIRED') {
      errorMessage = 'Se requiere especificar el tipo de documento';
    } else if (error.graphQLErrors?.[0]?.extensions?.code === 'INVALID_DOCUMENT_STRUCTURE') {
      errorMessage = 'El documento tiene un formato inválido';
    }
    
    return <div className="legal-document error">{errorMessage}</div>;
  }

  if (!data || !data.legalDocument) {
    return <div className="legal-document error">No se encontró el documento</div>;
  }

  const { title, content, version, lastUpdated, language } = data.legalDocument;

  const renderContent = (content) => {
    if (typeof content === 'string') {
      return <p className="content-text">{content}</p>;
    }
    if (Array.isArray(content)) {
      return (
        <ul className="content-list">
          {content.map((item, index) => (
            <li key={index} className="content-list-item">
              {typeof item === 'string' ? item : renderContent(item)}
            </li>
          ))}
        </ul>
      );
    }
    if (typeof content === 'object') {
      return (
        <div className="content-object">
          {Object.entries(content).map(([key, value]) => (
            <div key={key} className="content-section">
              <h3 className="content-section-title">{key.replace(/_/g, ' ').toUpperCase()}</h3>
              {renderContent(value)}
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  // Parse the JSON strings in the content array
  const parsedSections = content.map(section => JSON.parse(section));

  return (
    <div className="legal-document">
      <div className="document-header">
        <h1 className="document-title">{title}</h1>
        <div className="document-meta">
          <p className="document-version">Versión: {version}</p>
          <p className="document-date">Última actualización: {new Date(lastUpdated).toLocaleDateString('es-ES')}</p>
        </div>
      </div>
      <div className="document-content">
        {parsedSections.map((section, index) => (
          <div key={index} className="document-section">
            <h2 className="section-title">{section.title}</h2>
            {renderContent(section.content)}
          </div>
        ))}
      </div>
    </div>
  );
};

export default LegalDocument; 