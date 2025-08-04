import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyP2P.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyP2P = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const paymentMethods = [
    { name: 'Pago Móvil', country: '🇻🇪', icon: '📱' },
    { name: 'Mercado Pago', country: '🇦🇷', icon: '💳' },
    { name: 'Nequi', country: '🇨🇴', icon: '📲' },
    { name: 'Yape', country: '🇵🇪', icon: '💰' },
    { name: 'PIX', country: '🇧🇷', icon: '⚡' },
    { name: 'SPEI', country: '🇲🇽', icon: '🏦' },
  ];

  const benefits = [
    {
      icon: '🔄',
      title: t('Cambio al instante', 'Instant exchange', '즉시 환전'),
      description: t('Convierte entre dólares digitales y tu moneda local en segundos', 'Convert between digital dollars and your local currency in seconds', '디지털 달러와 현지 통화를 몇 초 만에 변환')
    },
    {
      icon: '💸',
      title: t('Mejores tasas', 'Better rates', '더 나은 환율'),
      description: t('Precios competitivos directamente entre usuarios, sin intermediarios', 'Competitive prices directly between users, no intermediaries', '중개자 없이 사용자 간 직접 경쟁력 있는 가격')
    },
    {
      icon: '🛡️',
      title: t('Vendedores Verificados', 'Verified Sellers', '검증된 판매자'),
      description: t('Solo operamos con vendedores verificados y con buena reputación', 'We only work with verified sellers with good reputation', '평판이 좋은 검증된 판매자와만 거래')
    },
    {
      icon: '🌎',
      title: t('Multi-país', 'Multi-country', '다국가 지원'),
      description: t('Opera con métodos de pago de toda América Latina', 'Operate with payment methods from all of Latin America', '라틴 아메리카 전체의 결제 방법으로 운영')
    }
  ];

  return (
    <section className={styles.p2p} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>🔥 {t('INTERCAMBIO P2P', 'P2P EXCHANGE', 'P2P 거래소')}</span>
          <h2 className={styles.title}>
            {t('Cambia dólares por tu', 'Exchange dollars for your', '달러를 당신의')}
            <span className={styles.highlight}> {t('moneda local', 'local currency', '현지 통화로 교환')}</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Los vendedores aceptan estos métodos de pago populares en cada país', 'Sellers accept these popular payment methods in each country', '판매자들은 각 국가에서 인기 있는 결제 방법을 수락합니다')}
          </p>
        </motion.div>

        {/* Payment Methods Showcase */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.2 }}
          className={styles.paymentMethods}
        >
          <h3 className={styles.methodsTitle}>{t('Métodos de pago disponibles', 'Available payment methods', '사용 가능한 결제 방법')}</h3>
          <div className={styles.methodsGrid}>
            {paymentMethods.map((method, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={inView ? { opacity: 1, scale: 1 } : {}}
                transition={{ duration: 0.3, delay: 0.1 * index }}
                className={styles.methodCard}
              >
                <span className={styles.methodIcon}>{method.icon}</span>
                <div className={styles.methodInfo}>
                  <p className={styles.methodName}>{method.name}</p>
                  <p className={styles.methodCountry}>{method.country}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Benefits */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.3 }}
          className={styles.benefits}
        >
          {benefits.map((benefit, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 20 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.4, delay: 0.1 * index }}
              className={styles.benefitCard}
            >
              <div className={styles.benefitIcon}>{benefit.icon}</div>
              <h4 className={styles.benefitTitle}>{benefit.title}</h4>
              <p className={styles.benefitDescription}>{benefit.description}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyP2P;