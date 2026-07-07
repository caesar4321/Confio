import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import { useQuery } from '@apollo/client';
import styles from '../../styles/FriendlyTestimonials.module.css';
import { useLanguage } from '../../contexts/LanguageContext';
import { LANDING_STATS, fmtUsd, toStatValue } from './landingStats';

const FriendlyTestimonials = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  // Anonymized user voices (live-app era; no waiting-list framing)
  const testimonials = [
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇻🇪 Venezuela',
      text: t('Envío dinero a mi familia sin las comisiones absurdas de los bancos. Les llega en segundos.', 'I send money to my family without the absurd bank fees. It reaches them in seconds.', '터무니없는 은행 수수료 없이 가족에게 돈을 보냅니다. 몇 초 만에 도착해요.')
    },
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇦🇷 Argentina',
      text: t('La inflación ya no me quita el sueño. Mis ahorros están en dólares digitales, protegidos.', "Inflation doesn't keep me up at night anymore. My savings are in digital dollars, protected.", '인플레이션 걱정이 사라졌습니다. 제 저축은 디지털 달러로 보호받고 있어요.')
    },
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇲🇽 México',
      text: t('Mis clientes internacionales me pagan en dólares digitales, al instante y sin complicaciones.', 'My international clients pay me in digital dollars, instantly and without complications.', '해외 고객들이 디지털 달러로 즉시, 복잡함 없이 결제합니다.')
    }
  ];

  const { data: statsData } = useQuery(LANDING_STATS, { fetchPolicy: 'cache-and-network' });
  const live = statsData?.landingStats;

  // Live values only — no hardcoded fallbacks (DESIGN.md: real numbers or
  // nothing). Stats without finite positive data simply don't render.
  const deposited = toStatValue(live?.depositedVolumeUsd);
  const presale = toStatValue(live?.presaleRaisedUsd);
  const stats = [
    deposited != null && {
      number: fmtUsd(deposited),
      label: t('Volumen depositado on-chain', 'On-chain deposited volume', '온체인 입금 총액')
    },
    presale != null && {
      number: fmtUsd(presale),
      label: t('Recaudado en preventa $CONFIO', 'Raised in $CONFIO presale', '$CONFIO 프리세일 모금액')
    },
    { number: t('Gratis', 'Free', '무료'), label: t('Para usuarios normales', 'For regular users', '일반 사용자를 위해') }
  ].filter(Boolean);

  return (
    <section className={styles.testimonials} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('COMUNIDAD', 'COMMUNITY', '커뮤니티')}</span>
          <h2 className={styles.title}>
            {t('Miles ya confían en', 'Thousands already trust', '수천 명이 이미 신뢰하는')}
            <span className={styles.highlight}> Confío</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Únete a las miles de personas que ya usan la app en América Latina', 'Join the thousands of people already using the app across Latin America', '라틴 아메리카에서 이미 앱을 사용 중인 수천 명과 함께하세요')}
          </p>
        </motion.div>

        <div className={styles.testimonialsGrid}>
          {testimonials.map((testimonial, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.1 * index }}
              className={styles.testimonialCard}
            >
              <div className={styles.quote}>"</div>
              <p className={styles.testimonialText}>{testimonial.text}</p>
              <div className={styles.testimonialFooter}>
                <div className={styles.userInfo}>
                  <div className={styles.avatar}>👤</div>
                  <div>
                    <p className={styles.userName}>{testimonial.name}</p>
                    <p className={styles.userCountry}>{testimonial.country}</p>
                  </div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.4 }}
          className={styles.statsSection}
        >
          {stats.map((stat, index) => (
            <div key={index} className={styles.stat}>
              <h3 className={styles.statNumber}>{stat.number}</h3>
              <p className={styles.statLabel}>{stat.label}</p>
            </div>
          ))}
        </motion.div>

      </div>
    </section>
  );
};

export default FriendlyTestimonials;
