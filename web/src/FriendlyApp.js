import React, { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ApolloProvider } from '@apollo/client';
import client from './apollo/client';
import { LanguageProvider } from './contexts/LanguageContext';

// Friendly Fintech Components
import LanguageSwitcher from './Components/LandingPage/LanguageSwitcher';
import FriendlyHeroSection from './Components/LandingPage/FriendlyHeroSection';
import FriendlyFeatures from './Components/LandingPage/FriendlyFeatures';
import FriendlyHowItWorks from './Components/LandingPage/FriendlyHowItWorks';
import FriendlyAssets from './Components/LandingPage/FriendlyAssets';
import FriendlyRoadmap from './Components/LandingPage/FriendlyRoadmap';
import FriendlyFeeStructure from './Components/LandingPage/FriendlyFeeStructure';
import FriendlyTestimonials from './Components/LandingPage/FriendlyTestimonials';
import FriendlyFounder from './Components/LandingPage/FriendlyFounder';
import FriendlyFooter from './Components/LandingPage/FriendlyFooter';

// Legal pages
import TermsPage from './Components/LegalDocument/TermsPage';
import PrivacyPage from './Components/LegalDocument/PrivacyPage';
import DeletionPage from './Components/LegalDocument/DeletionPage';
import TransactionVerificationPage from './Components/Verification/TransactionVerificationPage';

import './FriendlyApp.css';

function FriendlyApp() {
  useEffect(() => {
    // Set page title based on user language
    const titles = {
      es: 'Confío: PayPal de América Latina',
      en: 'Confío: PayPal of Latin America',
      ko: 'Confío: 라틴 아메리카의 PayPal',
      default: 'Confío: PayPal de América Latina'
    };

    const lang = (navigator.language || navigator.userLanguage).slice(0, 2);
    document.title = titles[lang] || titles.default;

    // Add smooth scrolling
    document.documentElement.style.scrollBehavior = 'smooth';

    // Theme color for mobile browsers
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
      metaThemeColor.content = '#34d399'; // Friendly green
    }

    // Add friendly font
    const link = document.createElement('link');
    link.href = 'https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap';
    link.rel = 'stylesheet';
    document.head.appendChild(link);
  }, []);

  return (
    <ApolloProvider client={client}>
      <LanguageProvider>
        <Router>
          <div className="FriendlyApp">
            <Routes>
              <Route path="/" element={
                <>
                  <LanguageSwitcher />
                  <main>
                    <FriendlyHeroSection />
                    <FriendlyFeatures />
                    <FriendlyHowItWorks />
                    <FriendlyAssets />
                    <FriendlyRoadmap />
                    <FriendlyFeeStructure />
                    <FriendlyTestimonials />
                    <FriendlyFounder />
                  </main>
                  <FriendlyFooter />
                </>
              } />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/deletion" element={<DeletionPage />} />
              <Route path="/verify/:hash" element={<TransactionVerificationPage />} />
            </Routes>
          </div>
        </Router>
      </LanguageProvider>
    </ApolloProvider>
  );
}

export default FriendlyApp;
