import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/TokensSection.module.css';
import cUSDLogo from '../../images/cUSD.png';
import confioLogo from '../../images/CONFIO.png';

const TokensSection = () => {
  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.title}
        >
          Nuestros activos: Confío Dollar($cUSD) y Confío($CONFIO)
        </motion.h2>

        <div className={styles.tokens}>
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8 }}
            className={styles.tokenCard}
          >
            <div className={styles.tokenHeader}>
              <img src={cUSDLogo} alt="Confío Dollar($cUSD)" className={styles.tokenIcon} />
              <h3 className={styles.tokenTitle}>Confío Dollar($cUSD)</h3>
            </div>
            <div className={styles.tokenInfo}>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>¿Qué es?</span>
                <span className={styles.infoValue}>Dólar digital estable</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Respaldado por</span>
                <span className={styles.infoValue}>100% USDC</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Uso principal</span>
                <span className={styles.infoValue}>Envíos, pagos, ahorro</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Valor</span>
                <span className={styles.infoValue}>Estable (1:1 con USDC)</span>
              </div>
            </div>
            <div className={styles.tokenNote}>
              🛡 Confío Dollar($cUSD) está respaldado 100% por USDC, el dólar digital más confiable del mundo.
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8 }}
            className={styles.tokenCard}
          >
            <div className={styles.tokenHeader}>
              <img src={confioLogo} alt="Confío($CONFIO)" className={styles.tokenIcon} />
              <h3 className={styles.tokenTitle}>Confío($CONFIO)</h3>
            </div>
            <div className={styles.tokenInfo}>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>¿Qué es?</span>
                <span className={styles.infoValue}>Token de la comunidad</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Respaldado por</span>
                <span className={styles.infoValue}>Confianza, utilidad, futuro</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Uso principal</span>
                <span className={styles.infoValue}>Recompensas, misiones, beneficios</span>
              </div>
              <div className={styles.infoRow}>
                <span className={styles.infoLabel}>Valor</span>
                <span className={styles.infoValue}>Variable</span>
              </div>
            </div>
            <div className={styles.tokenNote}>
              💡 Confío($CONFIO) es para quienes creen en el futuro de esta comunidad.
            </div>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={styles.documentButtons}
        >
          <a 
            href="https://medium.com/confio4world/duende-cryptocurrency-and-its-exclusive-payment-platform-to-facilitate-cryptocurrency-mass-c0a7499d0e81"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.documentButton}
          >
            📄 Whitepaper
          </a>
          <a 
            href="https://docs.google.com/presentation/d/1wRK7VE90fOZT8rqx2My61GKYJt7SPtum9ZMO2F1CK1Q/edit?usp=sharing"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.documentButton}
          >
            📊 Pitchdeck
          </a>
        </motion.div>
      </div>
    </section>
  );
};

export default TokensSection; 