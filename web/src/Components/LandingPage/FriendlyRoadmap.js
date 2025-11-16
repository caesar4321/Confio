import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyRoadmap.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyRoadmap = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const roadmapItems = [
    {
      quarter: 'Q4 2025',
      title: t('Lanzamiento en Venezuela', 'Launch in Venezuela', '베네수엘라 출시'),
      description: t(
        'Apertura oficial para usuarios en Venezuela con P2P Exchange completo, retrasado por el rechazo de entrada del fundador Julián en Venezuela. Pivotando el primer mercado principal hacia Argentina.',
        'Official opening for users in Venezuela with the complete P2P Exchange, delayed because founder Julian was denied entry into Venezuela. Pivoting the first principal market toward Argentina.',
        '베네수엘라 사용자를 위한 전체 P2P 거래소 공식 출시는 창업자 줄리안의 베네수엘라 입국 거부로 지연되었습니다. 첫 번째 핵심 시장을 아르헨티나로 전환하고 있습니다.'
      ),
      icon: '🇻🇪',
      status: 'active'
    },
    {
      quarter: 'Q1 2026',
      title: t('Alianzas Onramp, integraciones automáticas y primera preventa', 'Onramp partnerships, automatic integrations, and first presale', '온램프 파트너십, 자동 통합 및 첫 사전 판매'),
      description: t(
        'Integración con socios Onramp para que los usuarios recarguen dólares automáticamente desde sus bancos o apps fintech favoritas, junto a la primera preventa oficial de $CONFIO.',
        'Partnering and integrating with Onramps so users can top up dollar balances automatically from their favorite banks or fintech apps, plus the first official $CONFIO presale.',
        '사용자가 선호하는 은행이나 핀테크 앱에서 자동으로 달러 잔액을 충전할 수 있도록 온램프 파트너와 통합하고, 첫 공식 $CONFIO 사전 판매를 진행합니다.'
      ),
      icon: '🚀',
      status: 'upcoming'
    },
    {
      quarter: 'Q2 2026',
      title: t('Lanzamiento en Argentina', 'Launch in Argentina', '아르헨티나 출시'),
      description: t('Apertura para usuarios argentinos con métodos de pago locales', 'Opening for Argentine users with local payment methods', '현지 결제 방법으로 아르헨티나 사용자를 위한 오픈'),
      icon: '🇦🇷',
      status: 'upcoming'
    },
    {
      quarter: 'Q3 2026',
      title: t('Segunda Preventa $CONFIO', 'Second $CONFIO Presale', '두 번째 $CONFIO 사전 판매'),
      description: t('Crecimiento en Argentina y segunda ronda de preventa', 'Growth in Argentina and second presale round', '아르헨티나 성장 및 두 번째 사전 판매 라운드'),
      icon: '💎',
      status: 'upcoming'
    },
    {
      quarter: 'Q4 2026',
      title: t('Expansión a Bolivia', 'Expansion to Bolivia', '볼리비아 확장'),
      description: t('Lanzamiento completo en Bolivia y consolidación regional', 'Complete launch in Bolivia and regional consolidation', '볼리비아 완전 출시 및 지역 통합'),
      icon: '🇧🇴',
      status: 'upcoming'
    }
  ];

  return (
    <section className={styles.roadmap} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>📍 {t('NUESTRO CAMINO', 'OUR PATH', '우리의 길')}</span>
          <h2 className={styles.title}>
            Roadmap <span className={styles.highlight}>2025-2026</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Comenzamos en Venezuela, expandimos a Argentina y Bolivia. Paso a paso, país por país.', 'We start in Venezuela, expand to Argentina and Bolivia. Step by step, country by country.', '베네수엘라에서 시작하여 아르헨티나와 볼리비아로 확장합니다. 한 걸음씩, 한 나라씩.')}
          </p>
        </motion.div>

        <div className={styles.timeline}>
          {roadmapItems.map((item, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, x: index % 2 === 0 ? -50 : 50 }}
              animate={inView ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.1 * index }}
              className={`${styles.timelineItem} ${index % 2 === 0 ? styles.left : styles.right}`}
            >
              <div className={styles.timelineContent}>
                <div className={styles.timelineIcon}>{item.icon}</div>
                <div className={styles.timelineCard}>
                  <span className={`${styles.timelineQuarter} ${item.status === 'active' ? styles.active : ''}`}>
                    {item.quarter}
                  </span>
                  <h3 className={styles.timelineTitle}>{item.title}</h3>
                  <p className={styles.timelineDescription}>{item.description}</p>
                </div>
              </div>
              <div className={`${styles.timelineDot} ${item.status === 'active' ? styles.activeDot : ''}`} />
            </motion.div>
          ))}
          <div className={styles.timelineLine} />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.5 }}
          className={styles.footer}
        >
          <p className={styles.footerText}>
            💡 <strong>{t('Estrategia inteligente:', 'Smart strategy:', '스마트 전략:')}</strong> {t('Comenzamos pequeño, aprendemos rápido, escalamos con confianza', 'We start small, learn fast, scale with confidence', '작게 시작하고, 빠르게 배우고, 자신 있게 확장합니다')}
          </p>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyRoadmap;
