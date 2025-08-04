import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/ModernFooter.module.css';

const ModernFooter = () => {
  const currentYear = new Date().getFullYear();

  return (
    <footer className={styles.footer}>
      <div className={styles.container}>
        <div className={styles.content}>
          {/* Brand Section */}
          <div className={styles.brand}>
            <div className={styles.logo}>
              <span className={styles.logoIcon}>💎</span>
              <span className={styles.logoText}>Confío</span>
            </div>
            <p className={styles.tagline}>
              Tu wallet digital para América Latina.
              Envía, recibe y ahorra en dólares digitales.
            </p>
            <div className={styles.social}>
              <a href="https://t.me/confioapp" target="_blank" rel="noopener noreferrer" className={styles.socialLink}>
                <span>💬</span>
              </a>
              <a href="https://twitter.com/confioapp" target="_blank" rel="noopener noreferrer" className={styles.socialLink}>
                <span>🐦</span>
              </a>
              <a href="https://tiktok.com/@julianmoonluna" target="_blank" rel="noopener noreferrer" className={styles.socialLink}>
                <span>📱</span>
              </a>
              <a href="https://instagram.com/confioapp" target="_blank" rel="noopener noreferrer" className={styles.socialLink}>
                <span>📷</span>
              </a>
            </div>
          </div>

          {/* Links Sections */}
          <div className={styles.links}>
            <div className={styles.linkSection}>
              <h4 className={styles.linkTitle}>Producto</h4>
              <ul className={styles.linkList}>
                <li><a href="#features">Características</a></li>
                <li><a href="#how-it-works">Cómo Funciona</a></li>
                <li><a href="#tokens">Tokens Soportados</a></li>
                <li><a href="#p2p">P2P Exchange</a></li>
              </ul>
            </div>

            <div className={styles.linkSection}>
              <h4 className={styles.linkTitle}>Recursos</h4>
              <ul className={styles.linkList}>
                <li><a href="/help">Centro de Ayuda</a></li>
                <li><a href="/blog">Blog</a></li>
                <li><a href="/api">API Docs</a></li>
                <li><a href="/security">Seguridad</a></li>
              </ul>
            </div>

            <div className={styles.linkSection}>
              <h4 className={styles.linkTitle}>Compañía</h4>
              <ul className={styles.linkList}>
                <li><a href="#about">Sobre Nosotros</a></li>
                <li><a href="/careers">Carreras</a></li>
                <li><a href="/press">Prensa</a></li>
                <li><a href="/contact">Contacto</a></li>
              </ul>
            </div>

            <div className={styles.linkSection}>
              <h4 className={styles.linkTitle}>Legal</h4>
              <ul className={styles.linkList}>
                <li><a href="/terms">Términos de Servicio</a></li>
                <li><a href="/privacy">Privacidad</a></li>
                <li><a href="/deletion">Eliminar Cuenta</a></li>
                <li><a href="/compliance">Cumplimiento</a></li>
              </ul>
            </div>
          </div>
        </div>

        {/* Newsletter */}
        <div className={styles.newsletter}>
          <div className={styles.newsletterContent}>
            <div className={styles.newsletterText}>
              <h3>Mantente actualizado</h3>
              <p>Recibe las últimas noticias y actualizaciones de Confío</p>
            </div>
            <form className={styles.newsletterForm}>
              <input
                type="email"
                placeholder="tu@email.com"
                className={styles.newsletterInput}
              />
              <button type="submit" className={styles.newsletterButton}>
                Suscribirse
              </button>
            </form>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className={styles.bottom}>
          <div className={styles.copyright}>
            <p>© {currentYear} Confío. Todos los derechos reservados.</p>
            <p className={styles.openSource}>
              Código abierto • Construido con 💚 para LATAM
            </p>
          </div>
          
          <div className={styles.badges}>
            <div className={styles.badge}>
              <span className={styles.badgeIcon}>🔒</span>
              <span>Seguro</span>
            </div>
            <div className={styles.badge}>
              <span className={styles.badgeIcon}>⚡</span>
              <span>Rápido</span>
            </div>
            <div className={styles.badge}>
              <span className={styles.badgeIcon}>🌍</span>
              <span>Global</span>
            </div>
          </div>
        </div>
      </div>

      {/* Decorative Elements */}
      <div className={styles.decoration}>
        <div className={styles.gradientLine} />
      </div>
    </footer>
  );
};

export default ModernFooter;