import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyFeeStructure.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyFeeStructure = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  return (
    <section className={styles.feeStructure} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('TRANSPARENCIA TOTAL', 'TOTAL TRANSPARENCY', '완전한 투명성')}</span>
          <h2 className={styles.title}>
            {t('Tarifas', 'Fees', '수수료')} <span className={styles.highlight}>{t('Justas y Claras', 'Fair and Clear', '공정하고 투명한')}</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Sin letra pequeña, sin sorpresas. Esto es lo que pagas.', 'No fine print, no surprises. This is what you pay.', '작은 글씨 없음, 놀라움 없음. 이것이 당신이 지불하는 것입니다.')}
          </p>
        </motion.div>

        <div className={styles.cards}>
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.2 }}
            className={styles.card}
          >
            <div className={styles.cardHeader}>
              <span className={styles.userType}>{t('Usuario Personal', 'Personal User', '개인 사용자')}</span>
              <div className={styles.price}>
                <span className={styles.priceAmount}>{t('GRATIS', 'FREE', '무료')}</span>
                <span className={styles.pricePeriod}>{t('Para siempre', 'Forever', '영원히')}</span>
              </div>
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Perfecto para ti y tu familia', 'Perfect for you and your family', '당신과 가족에게 완벽함')}</h3>
              <ul className={styles.features}>
                <li>✅ {t('Envía y recibe dólares digitales al instante', 'Send and receive digital dollars instantly', '디지털 달러를 즉시 보내고 받기')}</li>
                <li>✅ {t('Paga en comercios con QR', 'Pay at businesses with QR', 'QR로 상점에서 결제')}</li>
                <li>✅ {t('Ahorra con rendimiento diario (cUSD+)', 'Save with daily yield (cUSD+)', '매일 수익이 쌓이는 저축 (cUSD+)')}</li>
                <li>✅ {t('Invierte en acciones de EE.UU.', 'Invest in U.S. stocks', '미국 주식에 투자')}</li>
                <li>✅ {t('Sin comisiones ocultas', 'No hidden fees', '숨겨진 수수료 없음')}</li>
              </ul>
              <div className={styles.freeHighlight}>
                <span className={styles.highlightIcon}>🎉</span>
                <span>{t('100% gratis, sin trucos', '100% free, no tricks', '100% 무료, 속임수 없음')}</span>
              </div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.3 }}
            className={`${styles.card} ${styles.businessCard}`}
          >
            <div className={styles.cardHeader}>
              <span className={styles.userType}>{t('Usuario Business', 'Business User', '비즈니스 사용자')}</span>
              <div className={styles.price}>
                <span className={styles.priceAmount}>0.9%</span>
                <span className={styles.pricePeriod}>{t('Por transacción', 'Per transaction', '거래당')}</span>
              </div>
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Ideal para tu negocio', 'Ideal for your business', '당신의 비즈니스에 이상적')}</h3>
              <ul className={styles.features}>
                <li>✅ {t('Todo lo del plan personal', 'Everything in personal plan', '개인 플랜의 모든 것')}</li>
                <li>✅ {t('Recibe pagos de clientes con QR', 'Receive customer payments with QR', 'QR로 고객 결제 수령')}</li>
                <li>✅ {t('Nómina para tus empleados', 'Payroll for your employees', '직원 급여(페이롤) 지급')}</li>
                <li>✅ {t('Empleados con roles (cajero, gerente)', 'Employees with roles (cashier, manager)', '역할별 직원 관리 (캐셔, 매니저)')}</li>
                <li>✅ {t('Soporte prioritario', 'Priority support', '우선 지원')}</li>
              </ul>
              <div className={styles.comparison}>
                <div className={styles.comparisonItem}>
                  <span className={styles.comparisonLabel}>{t('Tarjetas de crédito', 'Credit cards', '신용카드')}</span>
                  <span className={styles.comparisonValue}>3-5%</span>
                </div>
                <div className={styles.comparisonItem}>
                  <span className={styles.comparisonLabel}>{t('Tu ahorro con Confío', 'Your savings with Confío', 'Confío로 절약')}</span>
                  <span className={styles.comparisonValueGreen}>{t('Hasta 80% menos', 'Up to 80% less', '최대 80% 절감')}</span>
                </div>
              </div>
            </div>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.4 }}
          className={styles.footer}
        >
          <div className={styles.footerCard}>
            <span className={styles.footerIcon}>💡</span>
            <div>
              <h4 className={styles.footerTitle}>{t('¿Por qué es gratis para usuarios normales?', 'Why is it free for regular users?', '일반 사용자에게는 왜 무료인가요?')}</h4>
              <p className={styles.footerText}>
                {t('Creemos que todos merecen acceso a servicios financieros justos. Los negocios que procesan grandes volúmenes nos ayudan a mantener el servicio gratuito para todos los demás.', 'We believe everyone deserves access to fair financial services. Businesses that process large volumes help us keep the service free for everyone else.', '모든 사람이 공정한 금융 서비스에 접근할 자격이 있다고 믿습니다. 대량 처리하는 비즈니스가 다른 모든 사람에게 무료 서비스를 유지하는 데 도움이 됩니다.')}
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyFeeStructure;