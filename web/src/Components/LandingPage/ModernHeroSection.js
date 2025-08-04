import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/ModernHeroSection.module.css';

const ModernHeroSection = () => {
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    const handleMouseMove = (e) => {
      setMousePosition({ x: e.clientX, y: e.clientY });
    };

    const handleScroll = () => {
      setScrollY(window.scrollY);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('scroll', handleScroll);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('scroll', handleScroll);
    };
  }, []);

  return (
    <section className={styles.hero}>
      {/* Animated gradient background */}
      <div className={styles.gradientBg}>
        <div className={styles.gradientOrb1} />
        <div className={styles.gradientOrb2} />
        <div className={styles.gradientOrb3} />
      </div>

      {/* Floating elements */}
      <div className={styles.floatingElements}>
        <motion.div 
          className={styles.floatingCard}
          animate={{
            y: [0, -20, 0],
            rotate: [0, 5, 0]
          }}
          transition={{
            duration: 6,
            repeat: Infinity,
            ease: "easeInOut"
          }}
          style={{
            transform: `translateX(${mousePosition.x * 0.01}px) translateY(${mousePosition.y * 0.01}px)`
          }}
        >
          <span className={styles.cardIcon}>💳</span>
          <span className={styles.cardText}>Sin comisiones</span>
        </motion.div>

        <motion.div 
          className={styles.floatingCurrency}
          animate={{
            y: [0, 15, 0],
            rotate: [0, -5, 0]
          }}
          transition={{
            duration: 5,
            repeat: Infinity,
            ease: "easeInOut",
            delay: 1
          }}
          style={{
            transform: `translateX(${mousePosition.x * -0.015}px) translateY(${mousePosition.y * -0.015}px)`
          }}
        >
          <span className={styles.currencySymbol}>$</span>
        </motion.div>

        <motion.div 
          className={styles.floatingGlobe}
          animate={{
            y: [0, -15, 0],
            rotate: [0, 360]
          }}
          transition={{
            y: {
              duration: 7,
              repeat: Infinity,
              ease: "easeInOut"
            },
            rotate: {
              duration: 20,
              repeat: Infinity,
              ease: "linear"
            }
          }}
        >
          🌎
        </motion.div>
      </div>

      <div className={styles.heroContent}>
        {/* Animated badge */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className={styles.badge}
        >
          <span className={styles.badgeIcon}>🚀</span>
          <span className={styles.badgeText}>Nuevo en LATAM</span>
        </motion.div>

        {/* Main title with gradient text */}
        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={styles.title}
        >
          Tu dinero digital,
          <br />
          <span className={styles.gradientText}>sin fronteras</span>
        </motion.h1>

        {/* Subtitle with better typography */}
        <motion.p
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className={styles.subtitle}
        >
          Envía, recibe y ahorra en dólares digitales.
          <br />
          La wallet Web3 diseñada para latinoamérica.
        </motion.p>

        {/* Interactive stats */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.6 }}
          className={styles.stats}
        >
          <div className={styles.stat}>
            <span className={styles.statNumber}>0%</span>
            <span className={styles.statLabel}>Comisiones</span>
          </div>
          <div className={styles.statDivider} />
          <div className={styles.stat}>
            <span className={styles.statNumber}>24/7</span>
            <span className={styles.statLabel}>Disponible</span>
          </div>
          <div className={styles.statDivider} />
          <div className={styles.stat}>
            <span className={styles.statNumber}>2min</span>
            <span className={styles.statLabel}>Para empezar</span>
          </div>
        </motion.div>

        {/* CTA buttons with better design */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className={styles.ctaContainer}
        >
          <button className={styles.primaryCta}>
            <span className={styles.ctaIcon}>📱</span>
            <span className={styles.ctaText}>
              <span className={styles.ctaMain}>Descarga la App</span>
              <span className={styles.ctaSub}>iOS & Android</span>
            </span>
            <span className={styles.ctaArrow}>→</span>
          </button>

          <button className={styles.secondaryCta}>
            <span className={styles.playIcon}>▶</span>
            <span>Ver Demo</span>
          </button>
        </motion.div>

        {/* Trust indicators */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1, delay: 1 }}
          className={styles.trustIndicators}
        >
          <div className={styles.trustItem}>
            <span className={styles.trustIcon}>🔒</span>
            <span className={styles.trustText}>Blockchain Seguro</span>
          </div>
          <div className={styles.trustItem}>
            <span className={styles.trustIcon}>🏛</span>
            <span className={styles.trustText}>Regulado</span>
          </div>
          <div className={styles.trustItem}>
            <span className={styles.trustIcon}>👥</span>
            <span className={styles.trustText}>+10k usuarios</span>
          </div>
        </motion.div>
      </div>

      {/* Scroll indicator */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 1.5 }}
        className={styles.scrollIndicator}
      >
        <div className={styles.mouse}>
          <div className={styles.wheel} />
        </div>
        <span className={styles.scrollText}>Descubre más</span>
      </motion.div>
    </section>
  );
};

export default ModernHeroSection;