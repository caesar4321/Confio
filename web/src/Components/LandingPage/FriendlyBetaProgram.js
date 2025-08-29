import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyBetaProgram.module.css';
const pioneroBadge = process.env.PUBLIC_URL + '/images/PioneroBeta.png';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyBetaProgram = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const benefits = [
    t('🎯 Acceso exclusivo antes que nadie', '🎯 Exclusive access before anyone else', '🎯 누구보다 먼저 독점 액세스'),
    t('💎 Insignia Pionero Beta permanente', '💎 Permanent Pioneer Beta badge', '💎 영구 파이오니어 베타 배지'),
    t('🚀 Influye en el desarrollo del producto', '🚀 Influence product development', '🚀 제품 개발에 영향력 행사'),
    t('💰 Bonificaciones especiales en $CONFIO', '💰 Special $CONFIO bonuses', '💰 특별 $CONFIO 보너스'),
    t('👥 Comunidad exclusiva', '👥 Exclusive community', '👥 독점 커뮤니티'),
    t('🎁 Sorpresas y recompensas exclusivas', '🎁 Exclusive surprises and rewards', '🎁 독점 서프라이즈와 보상')
  ];

  return (
    <section className={styles.betaProgram} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.content}
        >
          <div className={styles.leftSide}>
            <span className={styles.badge}>🔥 {t('OPORTUNIDAD LIMITADA', 'LIMITED OPPORTUNITY', '한정 기회')}</span>
            <h2 className={styles.title}>
              {t('Sé de los primeros', 'Be among the first', '첫 번째')} <span className={styles.highlight}>10,000</span> {t('beta testers', 'beta testers', '베타 테스터가 되세요')}
            </h2>
            <p className={styles.subtitle}>
              {t('Únete al grupo exclusivo de pioneros que darán forma al futuro financiero de América Latina', 'Join the exclusive group of pioneers who will shape the financial future of Latin America', '라틴 아메리카의 금융 미래를 만들어갈 독점 파이오니어 그룹에 참여하세요')}
            </p>
            
            <div className={styles.benefits}>
              <h3 className={styles.benefitsTitle}>{t('¿Qué obtienes como Beta Tester?', 'What do you get as a Beta Tester?', '베타 테스터로서 무엇을 얻나요?')}</h3>
              <ul className={styles.benefitsList}>
                {benefits.map((benefit, index) => (
                  <motion.li
                    key={index}
                    initial={{ opacity: 0, x: -20 }}
                    animate={inView ? { opacity: 1, x: 0 } : {}}
                    transition={{ duration: 0.4, delay: 0.1 * index }}
                    className={styles.benefit}
                  >
                    {benefit}
                  </motion.li>
                ))}
              </ul>
            </div>

            <div className={styles.counter}>
              <div className={styles.counterItem}>
                <span className={styles.counterNumber}>420</span>
                <span className={styles.counterLabel}>{t('Ya registrados', 'Already registered', '이미 등록됨')}</span>
              </div>
              <div className={styles.counterItem}>
                <span className={styles.counterNumber}>9,580</span>
                <span className={styles.counterLabel}>{t('Cupos disponibles', 'Spots available', '사용 가능한 자리')}</span>
              </div>
            </div>
          </div>

          <div className={styles.rightSide}>
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={inView ? { opacity: 1, scale: 1 } : {}}
              transition={{ duration: 0.6, delay: 0.2 }}
              className={styles.badgeContainer}
            >
              <img src={pioneroBadge} alt="Pionero Beta Badge" className={styles.pioneroBadge} />
              <div className={styles.badgeGlow} />
            </motion.div>
            <p className={styles.badgeText}>
              {t('Esta insignia exclusiva aparecerá en tu perfil para siempre', 'This exclusive badge will appear on your profile forever', '이 독점 배지는 영원히 프로필에 표시됩니다')}
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyBetaProgram;
