import React from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import styles from '../../styles/LanguageSwitcher.module.css';

const LanguageSwitcher = () => {
  const { language, setLanguage } = useLanguage();

  return (
    <div className={styles.languageSwitcher}>
      <button
        className={`${styles.langButton} ${language === 'es' ? styles.active : ''}`}
        onClick={() => setLanguage('es')}
        aria-label="Español"
      >
        🇪🇸 ES
      </button>
      <button
        className={`${styles.langButton} ${language === 'en' ? styles.active : ''}`}
        onClick={() => setLanguage('en')}
        aria-label="English"
      >
        🇺🇸 EN
      </button>
      <button
        className={`${styles.langButton} ${language === 'ko' ? styles.active : ''}`}
        onClick={() => setLanguage('ko')}
        aria-label="한국어"
      >
        🇰🇷 KO
      </button>
    </div>
  );
};

export default LanguageSwitcher;