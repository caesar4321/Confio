import React, { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ApolloProvider } from '@apollo/client';
import client from './apollo/client';

// Modern Components
import ModernNavbar from './Components/layout/ModernNavbar';
import ModernHeroSection from './Components/LandingPage/ModernHeroSection';
import ModernFeatures from './Components/LandingPage/ModernFeatures';
import ModernHowItWorks from './Components/LandingPage/ModernHowItWorks';
import ModernTestimonials from './Components/LandingPage/ModernTestimonials';
import ModernFooter from './Components/LandingPage/ModernFooter';

// Original components that can be kept
import TokensSection from './Components/LandingPage/TokensSection';
import FounderSection from './Components/LandingPage/FounderSection';

// Legal pages
import TermsPage from './Components/LegalDocument/TermsPage';
import PrivacyPage from './Components/LegalDocument/PrivacyPage';
import DeletionPage from './Components/LegalDocument/DeletionPage';

import './ModernApp.css';

function ModernApp() {
  useEffect(() => {
    // Set page title based on user language
    const titles = {
      es: 'Confío - Tu Wallet Digital para LATAM',
      en: 'Confío - Your Digital Wallet for LATAM',
      default: 'Confío - Digital Wallet'
    };

    const lang = (navigator.language || navigator.userLanguage).slice(0, 2);
    document.title = titles[lang] || titles.default;

    // Add smooth scrolling behavior
    document.documentElement.style.scrollBehavior = 'smooth';

    // Theme color for mobile browsers
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
      metaThemeColor.content = '#0a0e27';
    }
  }, []);

  return (
    <ApolloProvider client={client}>
      <Router>
        <div className="ModernApp">
          <Routes>
            <Route path="/" element={
              <>
                <ModernNavbar />
                <main>
                  <section id="home">
                    <ModernHeroSection />
                  </section>
                  <section id="features">
                    <ModernFeatures />
                  </section>
                  <section id="how-it-works">
                    <ModernHowItWorks />
                  </section>
                  <section id="tokens">
                    <TokensSection />
                  </section>
                  <section id="testimonials">
                    <ModernTestimonials />
                  </section>
                  <section id="about">
                    <FounderSection />
                  </section>
                </main>
                <ModernFooter />
              </>
            } />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/deletion" element={<DeletionPage />} />
          </Routes>
        </div>
      </Router>
    </ApolloProvider>
  );
}

export default ModernApp;