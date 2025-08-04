import React, { createContext, useContext, useState, useEffect } from 'react';

const LanguageContext = createContext();

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};

export const LanguageProvider = ({ children }) => {
  const [language, setLanguage] = useState('es');

  useEffect(() => {
    // Detect browser language
    const browserLang = navigator.language || navigator.userLanguage;
    const langCode = browserLang.toLowerCase();
    
    // Check for Korean first, then Spanish, default to English
    let lang = 'en';
    if (langCode.startsWith('ko')) lang = 'ko';
    else if (langCode.startsWith('es')) lang = 'es';
    
    setLanguage(lang);
  }, []);

  const t = (es, en, ko) => {
    if (language === 'ko') return ko || en; // Fallback to English if Korean not provided
    if (language === 'es') return es;
    return en;
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};