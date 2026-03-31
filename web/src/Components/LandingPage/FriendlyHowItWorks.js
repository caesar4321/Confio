import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyHowItWorks.module.css';
import confioAppMockup from '../../images/ConfioApp.png';
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
      title: t('Regístrate con Google o Apple', 'Sign up with Google or Apple', '구글 또는 애플로 가입'),
      description: t('Un solo click y ya tienes tu cuenta. Sin formularios largos.', 'One click and you have your account. No long forms.', '한 번의 클릭으로 계정 생성. 긴 양식 없음.'),
      icon: '📱',
      color: '#34d399'
    },
    {
      number: '2',
      title: t('Compra tus dólares', 'Buy your dollars', '달러 구매'),
      description: t('Paga con tu método preferido y recibe dólares digitales al instante.', 'Pay with your preferred method and receive digital dollars instantly.', '선호하는 방법으로 결제하고 즉시 디지털 달러 받기.'),
      icon: '💵',
      color: '#f59e0b'
    },
    {
      number: '3',
      title: t('¡Usa tus dólares!', 'Use your dollars!', '달러 사용하기!'),
      description: t('Envía a familia y amigos solo con números de teléfono, paga en tiendas locales, todo gratis.', 'Send to family and friends with just phone numbers, pay at local stores, all for free.', '전화번호만으로 가족과 친구에게 보내고, 현지 상점에서 결제, 모두 무료.'),
      icon: '🎉',
      color: '#3b82f6'
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
          <span className={styles.badge}>⚡ {t('BETA: PROCESO SIMPLIFICADO', 'BETA: SIMPLIFIED PROCESS', '베타: 간소화된 프로세스')}</span>
          <h2 className={styles.title}>
            {t('Empieza a usar Confío en', 'Start using Confío in', 'Confío 사용 시작')}
            <span className={styles.highlight}> {t('minutos', 'minutes', '분 만에')}</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Sin papeleos, sin sucursales, sin complicaciones bancarias', 'No paperwork, no branches, no banking complications', '서류 작업 없음, 지점 방문 없음, 은행 복잡함 없음')}
          </p>
        </motion.div>

        <div className={styles.content}>
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.2 }}
            className={styles.stepsContainer}
          >
            {steps.map((step, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, x: -30 }}
                animate={inView ? { opacity: 1, x: 0 } : {}}
                transition={{ duration: 0.5, delay: 0.1 * index }}
                className={styles.step}
              >
                <div className={styles.stepNumber} style={{ background: step.color }}>
                  {step.number}
                </div>
                <div className={styles.stepContent}>
                  <div className={styles.stepIcon}>{step.icon}</div>
                  <h3 className={styles.stepTitle}>{step.title}</h3>
                  <p className={styles.stepDescription}>{step.description}</p>
                </div>
              </motion.div>
            ))}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.3 }}
            className={styles.mockupContainer}
          >
            <img 
              src={confioAppMockup} 
              alt="Confío App" 
              className={styles.mockup}
            />
            <div className={styles.floatingFeature}>
              <span>⚡</span>
              <span>Transferencias instantáneas</span>
            </div>
            <div className={styles.floatingFeature2}>
              <span>🔒</span>
              <span>100% Seguro</span>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
};

export default FriendlyHowItWorks;
