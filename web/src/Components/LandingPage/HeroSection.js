import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/HeroSection.module.css';
import confioLogo from '../../images/CONFIO.png';
import tiktokLogo from '../../images/TikTok.png';

const HeroSection = () => {
  return (
    <section className={styles.hero}>
      <div className={styles.heroContent}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.logoContainer}
        >
          <img
            src={confioLogo}
            alt="Confío Logo"
            className={styles.logo}
          />
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={styles.title}
        >
          Envía y paga en dólares digitales.
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className={styles.subtitle}
        >
          Sin bancos. Sin fronteras. Solo confianza.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.6 }}
          className={styles.ctaButtons}
        >
          <a
            href="https://tiktok.com/@julianmoonluna"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.primaryButton}
          >
            <img src={tiktokLogo} alt="TikTok" className={styles.socialIcon} />
            Mira el TikTok de Julian
          </a>
          <button className={styles.secondaryButton}>
            Ver mi historia
          </button>
        </motion.div>
      </div>
    </section>
  );
};

export default HeroSection;
