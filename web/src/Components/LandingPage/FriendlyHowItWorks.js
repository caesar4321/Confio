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
      title: t('Pedile lo que necesitás', 'Ask for what you need', '필요한 것을 요청하세요'),
      description: t('Escribilo o decilo, como a una persona. Confío lo prepara y te muestra el monto, la comisión y el total.', 'Type it or say it, the way you would to a person. Confío prepares it and shows you the amount, the fee and the total.', '사람에게 하듯 글이나 말로 요청하세요. Confío가 준비하고 금액, 수수료, 합계를 보여 줍니다.'),
    },
    {
      number: '3',
      title: t('Aprobalo con tu cara o tu huella', 'Approve it with your face or fingerprint', '얼굴이나 지문으로 승인하세요'),
      description: t('Nada se mueve sin tu firma. Si decís «no», Confío cancela en ese momento lo que preparó.', 'Nothing moves without your signature. If you say “no”, Confío cancels what it prepared right then.', '당신의 서명 없이는 아무것도 움직이지 않습니다. “아니요”라고 하면 Confío가 준비한 것을 그 자리에서 취소합니다.'),
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
