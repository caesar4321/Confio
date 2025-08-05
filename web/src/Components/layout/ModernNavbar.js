import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import styles from '../../styles/ModernNavbar.module.css';

const ModernNavbar = () => {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('home');

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 50);
      
      // Update active section based on scroll position
      const sections = ['home', 'features', 'how-it-works', 'tokens', 'about'];
      const scrollPosition = window.scrollY + 100;
      
      for (const section of sections) {
        const element = document.getElementById(section);
        if (element) {
          const { offsetTop, offsetHeight } = element;
          if (scrollPosition >= offsetTop && scrollPosition < offsetTop + offsetHeight) {
            setActiveSection(section);
            break;
          }
        }
      }
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navItems = [
    { id: 'home', label: 'Inicio', href: '#home' },
    { id: 'features', label: 'Características', href: '#features' },
    { id: 'how-it-works', label: 'Cómo Funciona', href: '#how-it-works' },
    { id: 'tokens', label: 'Tokens', href: '#tokens' },
    { id: 'about', label: 'Nosotros', href: '#about' },
  ];

  const scrollToSection = (e, sectionId) => {
    e.preventDefault();
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setIsMobileMenuOpen(false);
  };

  return (
    <>
      <motion.nav
        className={`${styles.navbar} ${isScrolled ? styles.scrolled : ''}`}
        initial={{ y: -100 }}
        animate={{ y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className={styles.navContainer}>
          {/* Logo */}
          <motion.div 
            className={styles.logo}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <div className={styles.logoIcon}>
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                <circle cx="16" cy="16" r="15" stroke="url(#gradient)" strokeWidth="2"/>
                <path d="M16 8C16 8 12 12 12 16C12 20 16 24 16 24C16 24 20 20 20 16C20 12 16 8 16 8Z" fill="url(#gradient)"/>
                <defs>
                  <linearGradient id="gradient" x1="0" y1="0" x2="32" y2="32">
                    <stop offset="0%" stopColor="#72D9BC"/>
                    <stop offset="100%" stopColor="#4A90E2"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <span className={styles.logoText}>Confío</span>
          </motion.div>

          {/* Desktop Navigation */}
          <div className={styles.desktopNav}>
            <ul className={styles.navList}>
              {navItems.map((item) => (
                <li key={item.id}>
                  <a
                    href={item.href}
                    onClick={(e) => scrollToSection(e, item.id)}
                    className={`${styles.navLink} ${activeSection === item.id ? styles.active : ''}`}
                  >
                    {item.label}
                    {activeSection === item.id && (
                      <motion.div
                        className={styles.activeIndicator}
                        layoutId="activeIndicator"
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                      />
                    )}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* CTA Buttons */}
          <div className={styles.navActions}>
            <button className={styles.loginBtn}>
              Iniciar Sesión
            </button>
            <button className={styles.downloadBtn}>
              <span className={styles.downloadIcon}>↓</span>
              Descargar App
            </button>
          </div>

          {/* Mobile Menu Toggle */}
          <button
            className={styles.mobileMenuToggle}
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            aria-label="Toggle mobile menu"
          >
            <div className={`${styles.hamburger} ${isMobileMenuOpen ? styles.open : ''}`}>
              <span></span>
              <span></span>
              <span></span>
            </div>
          </button>
        </div>
      </motion.nav>

      {/* Mobile Menu */}
      <AnimatePresence>
        {isMobileMenuOpen && (
          <motion.div
            className={styles.mobileMenu}
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
          >
            <div className={styles.mobileMenuContent}>
              <ul className={styles.mobileNavList}>
                {navItems.map((item, index) => (
                  <motion.li
                    key={item.id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.1 }}
                  >
                    <a
                      href={item.href}
                      onClick={(e) => scrollToSection(e, item.id)}
                      className={`${styles.mobileNavLink} ${activeSection === item.id ? styles.active : ''}`}
                    >
                      {item.label}
                    </a>
                  </motion.li>
                ))}
              </ul>

              <motion.div
                className={styles.mobileActions}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
              >
                <button className={styles.mobileLoginBtn}>
                  Iniciar Sesión
                </button>
                <button className={styles.mobileDownloadBtn}>
                  Descargar App
                </button>
              </motion.div>

              <motion.div
                className={styles.mobileSocial}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.7 }}
              >
                <a href="https://t.me/confioapp" target="_blank" rel="noopener noreferrer">
                  <span className={styles.socialIcon}>💬</span>
                </a>
                <a href="https://twitter.com/confioapp" target="_blank" rel="noopener noreferrer">
                  <span className={styles.socialIcon}>🐦</span>
                </a>
                <a href="https://tiktok.com/@julianmoonluna" target="_blank" rel="noopener noreferrer">
                  <span className={styles.socialIcon}>📱</span>
                </a>
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

export default ModernNavbar;