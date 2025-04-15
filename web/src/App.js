import React, { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import HeroSection from './Components/LandingPage/HeroSection';
import WhatIsConfio from './Components/LandingPage/WhatIsConfio';
import HowItWorks from './Components/LandingPage/HowItWorks';
import TokensSection from './Components/LandingPage/TokensSection';
import FounderSection from './Components/LandingPage/FounderSection';
import JoinSection from './Components/LandingPage/JoinSection';
import WhyTrustSection from './Components/LandingPage/WhyTrustSection';
import FloatingTelegramButton from './Components/LandingPage/FloatingTelegramButton';
import './App.css';

function App() {
  useEffect(() => {
    const titles = {
      es: 'Confío: Envía y paga en dólares digitales',
      en: 'Confío: Send and pay in digital dollars',
      default: 'Confío'
    };

    const lang = (navigator.language || navigator.userLanguage).slice(0, 2);
    document.title = titles[lang] || titles.default;
  }, []);

  return (
    <Router>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <HeroSection />
              <WhatIsConfio />
              <HowItWorks />
              <TokensSection />
              <WhyTrustSection />
              <FounderSection />
              <JoinSection />
              <FloatingTelegramButton />
            </>
          }
        />
      </Routes>
    </Router>
  );
}

export default App;
