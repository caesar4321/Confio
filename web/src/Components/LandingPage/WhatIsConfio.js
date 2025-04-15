import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/WhatIsConfio.module.css';
import confioAppImage from '../../images/ConfioApp.jpeg';

const WhatIsConfio = () => {
  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          whileInView={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.imageContainer}
        >
          <img
            src={confioAppImage}
            alt="Confío App"
            className={styles.appImage}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 20 }}
          whileInView={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.content}
        >
          <h2 className={styles.title}>¿Qué es Confío?</h2>
          <p className={styles.description}>
            Confío es una app que te permite enviar, recibir y pagar en dólares digitales ($cUSD) sin bancos, sin comisiones escondidas y sin complicaciones.
          </p>
          <p className={styles.description}>
            Hecha por un coreano que ama América Latina, para millones que merecen confiar otra vez.
          </p>

          <div className={styles.features}>
            <div className={styles.feature}>
              <div className={styles.icon}>📱</div>
              <p>Envía y recibe dólares digitales</p>
            </div>
            <div className={styles.feature}>
              <div className={styles.icon}>🔒</div>
              <p>Seguridad blockchain</p>
            </div>
            <div className={styles.feature}>
              <div className={styles.icon}>💸</div>
              <p>Sin comisiones escondidas</p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default WhatIsConfio; 