import React from 'react';
import { useQuery } from '@apollo/client';
import gql from 'graphql-tag';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../contexts/LanguageContext';
import styles from '../../styles/FriendlyLegalDocument.module.css';

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

const FriendlyLegalDocument = ({ type }) => {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const { loading, error, data } = useQuery(GET_LEGAL_DOCUMENT, {
    variables: { docType: type },
    fetchPolicy: 'network-only',
  });

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <div className={styles.spinner}></div>
          <p>{t('Cargando...', 'Loading...', '로딩 중...')}</p>
        </div>
      </div>
    );
  }

  if (error || !data?.legalDocument) {
    return (
      <div className={styles.container}>
        <div className={styles.error}>
          <span className={styles.errorIcon}>⚠️</span>
          <p>{t('Error al cargar el documento', 'Error loading document', '문서 로드 오류')}</p>
          <button onClick={() => navigate('/')} className={styles.backButton}>
            {t('Volver al inicio', 'Back to home', '홈으로 돌아가기')}
          </button>
        </div>
      </div>
    );
  }

  const { title, content, version, lastUpdated } = data.legalDocument;

  const renderContent = (content) => {
    if (typeof content === 'string') {
      return <p className={styles.paragraph}>{content}</p>;
    }
    if (Array.isArray(content)) {
      return (
        <ul className={styles.list}>
          {content.map((item, index) => (
            <li key={index} className={styles.listItem}>
              {typeof item === 'string' ? item : renderContent(item)}
            </li>
          ))}
        </ul>
      );
    }
    if (typeof content === 'object') {
      return (
        <div className={styles.contentObject}>
          {Object.entries(content).map(([key, value]) => (
            <div key={key} className={styles.subsection}>
              <h3 className={styles.subsectionTitle}>
                {key.replace(/_/g, ' ').toUpperCase()}
              </h3>
              {renderContent(value)}
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  // Parse the JSON strings in the content array
  const parsedSections = content.map(section => {
    try {
      return JSON.parse(section);
    } catch (e) {
      return { title: 'Section', content: section };
    }
  });

  return (
    <div className={styles.legalPage}>
      {/* Header with back button */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <button onClick={() => navigate('/')} className={styles.backLink}>
            ← {t('Volver', 'Back', '뒤로')}
          </button>
          <div className={styles.confioLogo}>Confío</div>
        </div>
      </div>

      {/* Document content */}
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className={styles.document}
        >
          <div className={styles.documentHeader}>
            <h1 className={styles.title}>{title}</h1>
            <div className={styles.meta}>
              <span className={styles.version}>
                {t('Versión', 'Version', '버전')}: {version}
              </span>
              <span className={styles.date}>
                {t('Última actualización', 'Last updated', '마지막 업데이트')}: {' '}
                {new Date(lastUpdated).toLocaleDateString()}
              </span>
            </div>
          </div>

          <div className={styles.content}>
            {parsedSections.map((section, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                className={styles.section}
              >
                <h2 className={styles.sectionTitle}>{section.title}</h2>
                {renderContent(section.content)}
              </motion.div>
            ))}
          </div>

          <div className={styles.footer}>
            <p className={styles.footerText}>
              {t(
                'Si tienes alguna pregunta sobre este documento, contáctanos en',
                'If you have any questions about this document, contact us at',
                '이 문서에 대한 질문이 있으시면 연락주세요'
              )}{' '}
              <a href="mailto:support@confio.lat" className={styles.emailLink}>
                support@confio.lat
              </a>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default FriendlyLegalDocument;