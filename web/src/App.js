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
import Footer from './Components/LandingPage/Footer';
import './App.css';

// Legal Pages Components
const TermsPage = () => {
  return (
    <div className="legal-container">
      <h1>Términos de Servicio</h1>
      <p className="last-updated">Última actualización: 2 de mayo de 2025</p>

      <section>
        <h2>1. Introducción</h2>
        <p>Bienvenido a Confío, la billetera abierta para la economía del dólar en América Latina. Al utilizar nuestros servicios, usted acepta estos términos. Por favor, léalos cuidadosamente.</p>
      </section>

      <section>
        <h2>2. Definiciones</h2>
        <ul>
          <li><strong>Confío</strong>: La plataforma y servicios proporcionados por Confío.</li>
          <li><strong>Usuario</strong>: Cualquier persona que utilice nuestros servicios.</li>
          <li><strong>Servicios</strong>: Incluye la billetera, transferencias y cualquier otra funcionalidad ofrecida por Confío.</li>
          <li><strong>Tokens</strong>: Incluye cUSD, CONFIO y cualquier otro token soportado.</li>
        </ul>
      </section>

      <section>
        <h2>3. Uso del Servicio</h2>
        <p>3.1. Para utilizar nuestros servicios, debe:</p>
        <ul>
          <li>Proporcionar información precisa y completa</li>
          <li>Mantener la seguridad de su cuenta</li>
          <li>Cumplir con todas las leyes aplicables</li>
        </ul>
      </section>

      <section>
        <h2>4. Transacciones y Tokens</h2>
        <p>4.1. Todas las transacciones son:</p>
        <ul>
          <li>Irreversibles una vez confirmadas en la blockchain</li>
          <li>Sin cargo de gas para el usuario final</li>
          <li>Procesadas a través de la blockchain Sui</li>
        </ul>
      </section>

      <section>
        <h2>5. Limitaciones de Responsabilidad</h2>
        <p>5.1. Confío no es responsable por:</p>
        <ul>
          <li>Pérdidas debido a errores del usuario</li>
          <li>Problemas de conectividad</li>
          <li>Fluctuaciones en el valor de los tokens</li>
          <li>Acciones de terceros</li>
        </ul>
      </section>

      <section>
        <h2>6. Modificaciones</h2>
        <p>Nos reservamos el derecho de modificar estos términos en cualquier momento. Los cambios entrarán en vigor al publicarlos en nuestro sitio web.</p>
      </section>

      <section>
        <h2>7. Contacto</h2>
        <p>Para preguntas sobre estos términos, contáctenos en:</p>
        <p>Email: legal@confio.lat</p>
        <p>Telegram: t.me/FansDeJulian</p>
      </section>

      <div className="back-link">
        <a href="/">← Volver a Confío</a>
      </div>
    </div>
  );
};

const PrivacyPage = () => {
  return (
    <div className="legal-container">
      <h1>Política de Privacidad</h1>
      <p className="last-updated">Última actualización: 2 de mayo de 2025</p>

      <section>
        <h2>1. Información que Recopilamos</h2>
        <p>1.1. Información personal:</p>
        <ul>
          <li>Dirección de correo electrónico</li>
          <li>Número de teléfono</li>
          <li>Direcciones de billetera</li>
          <li>Información de transacciones</li>
        </ul>
      </section>

      <section>
        <h2>2. Uso de la Información</h2>
        <p>2.1. Utilizamos su información para:</p>
        <ul>
          <li>Proporcionar y mantener nuestros servicios</li>
          <li>Procesar transacciones</li>
          <li>Enviar actualizaciones importantes</li>
          <li>Mejorar nuestros servicios</li>
          <li>Cumplir con obligaciones legales</li>
        </ul>
      </section>

      <section>
        <h2>3. Compartir Información</h2>
        <p>3.1. No compartimos su información personal con terceros excepto:</p>
        <ul>
          <li>Cuando es requerido por ley</li>
          <li>Para proteger nuestros derechos</li>
          <li>Con su consentimiento explícito</li>
        </ul>
      </section>

      <section>
        <h2>4. Seguridad</h2>
        <p>4.1. Medidas de seguridad:</p>
        <ul>
          <li>Encriptación de datos</li>
          <li>Acceso restringido a la información</li>
          <li>Monitoreo regular de seguridad</li>
          <li>Actualizaciones de seguridad</li>
        </ul>
      </section>

      <section>
        <h2>5. Sus Derechos</h2>
        <p>5.1. Usted tiene derecho a:</p>
        <ul>
          <li>Acceder a su información</li>
          <li>Corregir datos inexactos</li>
          <li>Solicitar la eliminación de datos</li>
          <li>Oponerse al procesamiento</li>
          <li>Exportar sus datos</li>
        </ul>
      </section>

      <section>
        <h2>6. Contacto</h2>
        <p>Para preguntas sobre privacidad, contáctenos en:</p>
        <p>Email: privacy@confio.lat</p>
        <p>Telegram: t.me/FansDeJulian</p>
      </section>

      <div className="back-link">
        <a href="/">← Volver a Confío</a>
      </div>
    </div>
  );
};

const DeletionPage = () => {
  return (
    <div className="legal-container">
      <h1>Eliminación de Datos</h1>
      <p className="last-updated">Última actualización: 2 de mayo de 2025</p>

      <section>
        <h2>1. Proceso de Eliminación</h2>
        <p>1.1. Para solicitar la eliminación de sus datos:</p>
        <ul>
          <li>Enviar un email a privacy@confio.lat</li>
          <li>Incluir "Solicitud de Eliminación de Datos" en el asunto</li>
          <li>Proporcionar su dirección de correo electrónico registrada</li>
          <li>Confirmar su identidad</li>
        </ul>
      </section>

      <section>
        <h2>2. Datos que se Eliminarán</h2>
        <p>2.1. Se eliminarán los siguientes datos:</p>
        <ul>
          <li>Información de la cuenta</li>
          <li>Historial de transacciones</li>
          <li>Preferencias de usuario</li>
          <li>Datos de contacto</li>
        </ul>
      </section>

      <section>
        <h2>3. Datos que no se Eliminarán</h2>
        <p>3.1. Por razones legales, mantendremos:</p>
        <ul>
          <li>Registros de transacciones en la blockchain</li>
          <li>Información requerida por ley</li>
          <li>Datos necesarios para prevenir fraudes</li>
        </ul>
      </section>

      <section>
        <h2>4. Tiempo de Procesamiento</h2>
        <p>4.1. Procesaremos su solicitud dentro de los 30 días hábiles.</p>
        <p>4.2. Recibirá una confirmación por email cuando se complete.</p>
      </section>

      <section>
        <h2>5. Consecuencias</h2>
        <p>5.1. Tenga en cuenta que:</p>
        <ul>
          <li>No podrá acceder a sus datos eliminados</li>
          <li>Deberá crear una nueva cuenta para usar nuestros servicios</li>
          <li>Las transacciones en la blockchain son permanentes</li>
        </ul>
      </section>

      <section>
        <h2>6. Contacto</h2>
        <p>Para preguntas sobre la eliminación de datos, contáctenos en:</p>
        <p>Email: privacy@confio.lat</p>
        <p>Telegram: t.me/FansDeJulian</p>
      </section>

      <div className="back-link">
        <a href="/">← Volver a Confío</a>
      </div>
    </div>
  );
};

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
              <Footer />
            </>
          }
        />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/deletion" element={<DeletionPage />} />
      </Routes>
    </Router>
  );
}

export default App;
