import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyTestimonials.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyTestimonials = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  // Anonymized waiting list testimonials
  const testimonials = [
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇻🇪 Venezuela',
      text: t('Llevo 3 meses esperando esta app. Por fin podré enviar dinero a mi familia sin las comisiones absurdas de los bancos.', "I've been waiting 3 months for this app. Finally I'll be able to send money to my family without the absurd bank fees.", '이 앱을 3개월 동안 기다렸습니다. 드디어 터무니없는 은행 수수료 없이 가족에게 돈을 보낼 수 있게 되었습니다.'),
      waitTime: t('En lista de espera: 3 meses', 'On waiting list: 3 months', '대기 리스트: 3개월')
    },
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇦🇷 Argentina',
      text: t('Ya no puedo más con la inflación. Necesito esta app YA para proteger mis ahorros en dólares digitales.', "I can't take inflation anymore. I need this app NOW to protect my savings in digital dollars.", '더 이상 인플레이션을 견딜 수 없습니다. 디지털 달러로 저축을 보호하기 위해 지금 당장 이 앱이 필요합니다.'),
      waitTime: t('En lista de espera: 2 meses', 'On waiting list: 2 months', '대기 리스트: 2개월')
    },
    {
      name: t('Usuario anónimo', 'Anonymous user', '익명 사용자'),
      country: '🇲🇽 México',
      text: t('Mis clientes internacionales quieren pagarme en dólares digitales. Confío será la solución perfecta.', 'My international clients want to pay me in digital dollars. Confío will be the perfect solution.', '제 국제 고객들이 디지털 달러로 결제하길 원합니다. Confío가 완벽한 솔루션이 될 것입니다.'),
      waitTime: t('En lista de espera: 1 mes', 'On waiting list: 1 month', '대기 리스트: 1개월')
    }
  ];

  const stats = [
    { number: '9000+', label: t('Miembros en el grupo de Telegram', 'Telegram group members', 'Telegram 그룹 멤버') },
    { number: '2700+', label: t('Usuarios activos de la app', 'Active app users', '앱 활성 사용자') },
    { number: '21+', label: t('Países (LATAM, EEUU, España)', 'Countries (LATAM, USA, Spain)', '국가 (라틴 아메리카, 미국, 스페인)') },
    { number: t('Gratis', 'Free', '무료'), label: t('Para usuarios normales', 'For regular users', '일반 사용자를 위해') }
  ];

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
            {t('Miles esperan por', 'Thousands wait for', '수천 명이 기다리는')}
            <span className={styles.highlight}> Confío</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Únete a la lista de espera y sé de los primeros en usar la app', 'Join the waiting list and be among the first to use the app', '대기 리스트에 참여하고 앱을 처음 사용하는 사람이 되세요')}
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
                <p className={styles.waitTime}>{testimonial.waitTime}</p>
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
