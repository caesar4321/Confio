import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/JoinSection.module.css';
import telegramLogo from '../../images/Telegram.png';

const JoinSection = () => {
  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.title}
        >
          <img src={telegramLogo} alt="Telegram" className={styles.socialIcon} />
          Únete a la comunidad
        </motion.h2>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={styles.content}
        >
          <div className={styles.socialButtons}>
            <a
              href="https://t.me/FansDeJulian"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.telegramButton}
            >
              <span className={styles.telegramIcon}>📱</span>
              Grupo Oficial de Telegram
            </a>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default JoinSection; 