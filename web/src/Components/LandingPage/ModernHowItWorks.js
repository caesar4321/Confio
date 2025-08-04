import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/ModernHowItWorks.module.css';

const ModernHowItWorks = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });

  const steps = [
    {
      number: '01',
      title: 'Crea tu cuenta',
      description: 'Regístrate con Google o Apple en menos de 2 minutos',
      icon: '👤',
      color: 'step1'
    },
    {
      number: '02',
      title: 'Verifica tu identidad',
      description: 'Proceso simple y seguro para proteger tu cuenta',
      icon: '✅',
      color: 'step2'
    },
    {
      number: '03',
      title: 'Agrega fondos',
      description: 'Deposita usando métodos de pago locales o crypto',
      icon: '💳',
      color: 'step3'
    },
    {
      number: '04',
      title: 'Envía y recibe',
      description: 'Transfiere dinero instantáneamente a cualquier lugar',
      icon: '🚀',
      color: 'step4'
    }
  ];

  return (
    <section className={styles.howItWorks} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.label}>CÓMO FUNCIONA</span>
          <h2 className={styles.title}>
            Empieza en minutos,
            <span className={styles.gradientText}> no en días</span>
          </h2>
          <p className={styles.subtitle}>
            Proceso simple y transparente sin complicaciones bancarias
          </p>
        </motion.div>

        <div className={styles.stepsContainer}>
          {steps.map((step, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, x: -50 }}
              animate={inView ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6, delay: index * 0.1 }}
              className={styles.step}
            >
              <div className={styles.stepNumber}>
                <span className={styles.number}>{step.number}</span>
                <div className={styles.progressLine} />
              </div>
              
              <div className={`${styles.stepCard} ${styles[step.color]}`}>
                <div className={styles.iconWrapper}>
                  <span className={styles.icon}>{step.icon}</span>
                </div>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.stepDescription}>{step.description}</p>
              </div>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.5 }}
          className={styles.demo}
        >
          <div className={styles.demoContent}>
            <div className={styles.phoneFrame}>
              <div className={styles.phoneScreen}>
                <div className={styles.appDemo}>
                  {/* Animated demo content */}
                  <div className={styles.demoHeader}>
                    <span className={styles.demoLogo}>Confío</span>
                    <span className={styles.demoBalance}>$1,234.56</span>
                  </div>
                  <div className={styles.demoActions}>
                    <button className={styles.demoBtn}>Enviar</button>
                    <button className={styles.demoBtn}>Recibir</button>
                    <button className={styles.demoBtn}>P2P</button>
                  </div>
                  <div className={styles.demoTransactions}>
                    <div className={styles.transaction}>
                      <span>María López</span>
                      <span className={styles.amount}>+$50.00</span>
                    </div>
                    <div className={styles.transaction}>
                      <span>Juan García</span>
                      <span className={styles.amount}>-$25.00</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className={styles.demoText}>
              <h3>Ve la app en acción</h3>
              <p>Interfaz intuitiva diseñada para todos</p>
              <button className={styles.watchDemo}>
                <span>▶</span> Ver Demo Completo
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default ModernHowItWorks;