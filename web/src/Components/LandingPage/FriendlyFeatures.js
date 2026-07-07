import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyFeatures.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyFeatures = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const features = [
    {
      icon: '🔓',
      title: t('Código Abierto', 'Open Source', '오픈 소스'),
      description: t('Todo nuestro código es público y verificable. La confianza se gana con pruebas.', 'All our code is public and verifiable. Trust is earned with proof.', '모든 코드가 공개되어 검증 가능합니다. 신뢰는 증거로 얻는 것입니다.')
    },
    {
      icon: '💰',
      title: t('Sin Comisiones', 'No Fees', '수수료 없음'),
      description: t('Envía y recibe dólares digitales sin costos ocultos', 'Send and receive digital dollars with no hidden costs', '숨겨진 비용 없이 디지털 달러를 보내고 받으세요')
    },
    {
      icon: '⚡',
      title: t('Instantáneo', 'Instant', '즉시'),
      description: t('Transacciones en segundos, disponible las 24 horas', 'Transactions in seconds, available 24/7', '몇 초 만에 거래, 24시간 이용 가능')
    },
    {
      icon: '🔒',
      title: t('Seguro', 'Secure', '안전'),
      description: t('Tu dinero protegido con tecnología blockchain', 'Your money protected with blockchain technology', '블록체인 기술로 보호되는 당신의 돈')
    },
    {
      icon: '🌎',
      title: t('Para LATAM', 'For LATAM', '라틴 아메리카를 위해'),
      description: t('Diseñado especialmente para las necesidades de América Latina', 'Specially designed for Latin America\'s needs', '라틴 아메리카의 필요에 맞게 특별히 설계됨')
    },
    {
      icon: '📱',
      title: t('Fácil de Usar', 'Easy to Use', '사용하기 쉽다'),
      description: t('Solo necesitas tu celular, sin papeleos ni complicaciones', 'You only need your phone, no paperwork or complications', '휴대폰만 있으면 됩니다, 서류나 복잡함 없이')
    }
  ];

  return (
    <section className={styles.features} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('POR QUÉ CONFÍO', 'WHY CONFÍO', '왜 CONFÍO인가')}</span>
          <h2 className={styles.title}>
            {t('Todo lo que necesitas,', 'Everything you need,', '필요한 모든 것,')}
            <span className={styles.highlight}> {t('nada que no', 'nothing you don\'t', '불필요한 것은 없음')}</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Una app simple para manejar tus dólares digitales', 'A simple app to manage your digital dollars', '디지털 달러를 관리하는 간단한 앱')}
          </p>
        </motion.div>

        <div className={styles.featuresGrid}>
          {features.map((feature, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: index * 0.1 }}
              className={styles.featureCard}
            >
              <div className={styles.featureIcon}>{feature.icon}</div>
              <h3 className={styles.featureTitle}>{feature.title}</h3>
              <p className={styles.featureDescription}>{feature.description}</p>
            </motion.div>
          ))}
        </div>

      </div>
    </section>
  );
};

export default FriendlyFeatures;