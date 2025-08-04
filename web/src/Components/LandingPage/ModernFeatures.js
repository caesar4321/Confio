import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/ModernFeatures.module.css';

const ModernFeatures = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });

  const features = [
    {
      icon: '⚡',
      title: 'Transacciones Instantáneas',
      description: 'Envía y recibe dinero en segundos, sin esperas bancarias.',
      gradient: 'gradient1'
    },
    {
      icon: '🔒',
      title: 'Seguridad Blockchain',
      description: 'Tu dinero protegido con la tecnología más segura del mundo.',
      gradient: 'gradient2'
    },
    {
      icon: '💰',
      title: 'Sin Comisiones Ocultas',
      description: 'Transparencia total. Paga solo lo que ves, sin sorpresas.',
      gradient: 'gradient3'
    },
    {
      icon: '🌍',
      title: 'Cobertura Global',
      description: 'Envía dinero a cualquier parte del mundo, sin fronteras.',
      gradient: 'gradient4'
    },
    {
      icon: '📱',
      title: 'App Intuitiva',
      description: 'Diseñada para todos, desde principiantes hasta expertos.',
      gradient: 'gradient5'
    },
    {
      icon: '🏦',
      title: 'P2P Exchange',
      description: 'Compra y vende crypto con métodos de pago locales.',
      gradient: 'gradient6'
    }
  ];

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1
      }
    }
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.6,
        ease: [0.4, 0, 0.2, 1]
      }
    }
  };

  return (
    <section className={styles.features} ref={ref}>
      <div className={styles.container}>
        {/* Section Header */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.label}>CARACTERÍSTICAS</span>
          <h2 className={styles.title}>
            Todo lo que necesitas en una
            <span className={styles.gradientText}> sola app</span>
          </h2>
          <p className={styles.subtitle}>
            Diseñada específicamente para las necesidades de América Latina
          </p>
        </motion.div>

        {/* Features Grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className={styles.grid}
        >
          {features.map((feature, index) => (
            <motion.div
              key={index}
              variants={itemVariants}
              className={styles.featureCard}
              whileHover={{ y: -5, transition: { duration: 0.2 } }}
            >
              <div className={`${styles.iconWrapper} ${styles[feature.gradient]}`}>
                <span className={styles.icon}>{feature.icon}</span>
              </div>
              <h3 className={styles.featureTitle}>{feature.title}</h3>
              <p className={styles.featureDescription}>{feature.description}</p>
              <div className={styles.featureHover}>
                <span className={styles.learnMore}>
                  Aprender más →
                </span>
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* CTA Section */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.4 }}
          className={styles.ctaSection}
        >
          <div className={styles.ctaContent}>
            <h3 className={styles.ctaTitle}>
              ¿Listo para empezar tu viaje financiero?
            </h3>
            <p className={styles.ctaText}>
              Únete a miles de usuarios que ya confían en nosotros
            </p>
          </div>
          <button className={styles.ctaButton}>
            Crear Cuenta Gratis
            <span className={styles.arrow}>→</span>
          </button>
        </motion.div>
      </div>
    </section>
  );
};

export default ModernFeatures;