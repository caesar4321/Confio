import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/WhyTrustSection.module.css';

const WhyTrustSection = () => {
  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.title}
        >
          ¿Por qué Confío?
        </motion.h2>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={styles.content}
        >
          <p className={styles.description}>
            En Venezuela 🇻🇪 y Argentina 🇦🇷, millones de personas han vivido algo que va más allá de los números:
            La hiperinflación no solo destruye el valor del dinero — también rompe la confianza.
          </p>

          <p className={styles.description}>
            Cuando el peso o el bolívar pierden su valor,
            no desaparece solo el poder adquisitivo.
            Desaparece la seguridad, la planificación, la esperanza.
          </p>

          <p className={styles.description}>
            Confío nace como una respuesta.
            Una app hecha por alguien que vivió esto de cerca,
            que cree que América Latina merece una alternativa estable,
            una moneda digital que sí mantiene su valor,
            y una comunidad que no depende de bancos ni gobiernos.
          </p>

          <p className={styles.description}>
            Porque confiar no debería ser un privilegio.
            Debería ser un derecho.
          </p>
        </motion.div>
      </div>
    </section>
  );
};

export default WhyTrustSection; 