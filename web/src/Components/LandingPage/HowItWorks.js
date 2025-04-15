import React from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/HowItWorks.module.css';

const steps = [
  {
    icon: '👤',
    title: 'Crea tu cuenta',
    description: 'Regístrate con tu correo o Google en segundos'
  },
  {
    icon: '💵',
    title: 'Carga dólares digitales',
    description: 'Carga cUSD o recibe pagos de otros usuarios'
  },
  {
    icon: '🚀',
    title: 'Envía o paga',
    description: 'Realiza transacciones con un solo clic'
  },
  {
    icon: '💬',
    title: 'Conversa si es necesario',
    description: 'Mantén la comunicación con la otra persona'
  }
];

const HowItWorks = () => {
  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className={styles.title}
        >
          ¿Cómo funciona?
        </motion.h2>

        <div className={styles.steps}>
          {steps.map((step, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: index * 0.2 }}
              className={styles.step}
            >
              <div className={styles.stepNumber}>{index + 1}</div>
              <div className={styles.stepIcon}>{step.icon}</div>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.stepDescription}>{step.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default HowItWorks; 