import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/FounderSection.module.css';
import founderImage from '../../images/JulianMoon_Founder.jpeg';

const FounderSection = () => {
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
            src={founderImage}
            alt="Julian Moon"
            className={styles.founderImage}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 20 }}
          whileInView={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.content}
        >
          <h2 className={styles.title}>Sobre el fundador</h2>
          <p className={styles.description}>
            Soy Julian Moon. Vine desde Corea, viví en toda América Latina.
            Vi algo que no podía ignorar: la desconfianza frena el progreso.
            Por eso, no solo hice una app. Hice una promesa:
            Devolver la confianza a esta región. Con tecnología. Con amor.
          </p>
          <div className={styles.quote}>
            <p className={styles.quoteText}>
              "No vine a traer otra app. Vine a traer una nueva forma de confiar."
            </p>
            <p className={styles.quoteAuthor}>— Julian Moon</p>
          </div>
          <a
            href="https://vm.tiktok.com/ZMSkc3Lk8/"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.storyButton}
          >
            Ver mi historia
          </a>
        </motion.div>
      </div>
    </section>
  );
};

export default FounderSection; 