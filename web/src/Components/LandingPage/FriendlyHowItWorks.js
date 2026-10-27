import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyHowItWorks.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyHowItWorks = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const steps = [
    {
      number: '1',
      title: t('Registrate con Google o Apple', 'Sign up with Google or Apple', '구글 또는 애플로 가입'),
      description: t('Un toque y ya tenés tu cuenta. Sin formularios largos.', 'One tap and you have your account. No long forms.', '한 번의 탭으로 계정 생성. 긴 양식 없음.'),
    },
    {
      number: '2',
      title: t('Recargá tus dólares', 'Top up your dollars', '달러 충전'),
      description: t('Desde tu banco o billetera, con el método de tu país. Antes de confirmar, ves cuánto recibís.', 'From your bank or wallet, with your country’s method. Before confirming, you see how much you receive.', '내 나라의 방법으로 은행이나 지갑에서 충전하세요. 확인 전에 받을 금액을 볼 수 있습니다.'),
    },
    {
      number: '3',
      title: t('Usalos como quieras', 'Use them your way', '원하는 대로 사용'),
      description: t('Enviá gratis a otros usuarios con su número de teléfono, invertí o comprá. Siempre ves la comisión exacta antes de confirmar.', 'Send free to other users with their phone number, invest or shop. You always see the exact fee before confirming.', '전화번호로 다른 사용자에게 무료로 보내고, 투자하거나 구매하세요. 확인 전에 항상 정확한 수수료를 볼 수 있습니다.'),
    }
  ];

  return (
    <section className={styles.howItWorks} ref={ref} id="asi-funciona">
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('ASÍ FUNCIONA', 'HOW IT WORKS', '작동 방식')}</span>
          <h2 className={styles.title}>
            {t('Empezá en', 'Start in', '시작은')}
            <span className={styles.highlight}> {t('minutos', 'minutes', '몇 분이면')}</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Sin papeleos, sin sucursales, sin complicaciones bancarias', 'No paperwork, no branches, no banking complications', '서류 작업 없음, 지점 방문 없음, 은행 복잡함 없음')}
          </p>
        </motion.div>

        <div className={styles.stepsContainer}>
          {steps.map((step, index) => (
            <motion.div
              key={step.number}
              initial={{ opacity: 0, y: 24 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.1 * index }}
              className={styles.step}
            >
              <div className={styles.stepNumber}>
                {step.number}
              </div>
              <div className={styles.stepContent}>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.stepDescription}>{step.description}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default FriendlyHowItWorks;
