import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/FloatingTelegramButton.module.css';
import telegramLogo from '../../images/Telegram.png';

const FloatingTelegramButton = () => {
  return (
    <motion.a
      href="https://t.me/confio4world"
      target="_blank"
      rel="noopener noreferrer"
      className={styles.floatingButton}
      whileHover={{ scale: 1.1 }}
      whileTap={{ scale: 0.95 }}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 1 }}
    >
      <img src={telegramLogo} alt="Telegram" className={styles.telegramIcon} />
      <span className={styles.tooltip}>Únete a nuestra comunidad</span>
    </motion.a>
  );
};

export default FloatingTelegramButton; 
