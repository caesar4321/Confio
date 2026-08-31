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

        <div className={styles.journeyIntro}>
          <span className={styles.journeyPill}>
            {t('La misma comisión de conversión para personas y negocios', 'The same conversion fee for people and businesses', '개인과 비즈니스 모두 동일한 전환 수수료')}
          </span>
          <p>
            {t('La comisión de conversión solo aplica al entrar o salir. Dentro de Confío, enviar y cambiar entre cUSD y cUSD+ es gratis; Confío Pay se cobra por separado.', 'The conversion fee only applies when entering or leaving. Inside Confío, sending and moving between cUSD and cUSD+ is free; Confío Pay is priced separately.', '전환 수수료는 들어오거나 나갈 때만 적용됩니다. Confío 안에서 송금하거나 cUSD와 cUSD+를 전환하는 것은 무료이며, Confío Pay는 별도로 부과됩니다.')}
          </p>
        </div>

        <div className={styles.cards} aria-label={t('Cómo funcionan las comisiones', 'How fees work', '수수료 적용 방식')}>
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.2 }}
            whileHover={{ y: -8 }}
            className={styles.card}
          >
            <div className={styles.cardHeader}>
              <span className={styles.stepLabel}>{t('ENTRAR', 'ENTER', '들어오기')}</span>
              <div className={styles.price}>
                <span className={styles.priceAmount}>{t('0,9%', '0.9%', '0.9%')}</span>
                <span className={styles.pricePeriod}>{t('una sola vez al convertir', 'once when converting', '전환할 때 한 번')}</span>
              </div>
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Convierte a dólares de Confío', 'Convert into Confío dollars', 'Confío 달러로 전환')}</h3>
              <p className={styles.cardText}>{t('Aplica al entrar desde moneda local o desde USDT, tanto para personas como para negocios.', 'Applies when entering from local currency or USDT, for both people and businesses.', '현지 통화 또는 USDT로 들어올 때 개인과 비즈니스 모두에게 적용됩니다.')}</p>
              <div className={styles.example}>
                <span>{t('Conviertes', 'You convert', '전환 금액')} US$100</span>
                <span>{t('Comisión de Confío US$0,90', 'Confío fee US$0.90', 'Confío 수수료 US$0.90')}</span>
                <strong>{t('Recibes US$99,10', 'You receive US$99.10', 'US$99.10 수령')}</strong>
              </div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.3 }}
            whileHover={{ y: -8 }}
            className={`${styles.card} ${styles.insideCard}`}
          >
            <div className={styles.cardHeader}>
              <span className={styles.stepLabel}>{t('DENTRO', 'INSIDE', '내부')}</span>
              <div className={styles.price}>
                <span className={styles.priceAmount}>0%</span>
                <span className={styles.pricePeriod}>{t('entre usuarios', 'between users', '사용자 간')}</span>
              </div>
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Tus dólares, en movimiento', 'Your dollars, in motion', '자유롭게 움직이는 달러')}</h3>
              <ul className={styles.features}>
                <li>✓ {t('Enviar y recibir entre usuarios', 'Send and receive between users', '사용자 간 송금과 수취')}</li>
                <li>✓ {t('Cambiar entre cUSD y cUSD+', 'Move between cUSD and cUSD+', 'cUSD와 cUSD+ 간 전환')}</li>
                <li>✓ {t('Sin membresías ni planes', 'No memberships or plans', '멤버십이나 요금제 없음')}</li>
              </ul>
              <div className={styles.freeHighlight}>
                <span className={styles.highlightIcon} aria-hidden="true">✓</span>
                <span>{t('Lo cotidiano sigue siendo gratis', 'Everyday movement stays free', '일상적인 자금 이동은 계속 무료')}</span>
              </div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.4 }}
            whileHover={{ y: -8 }}
            className={styles.card}
          >
            <div className={styles.cardHeader}>
              <span className={styles.stepLabel}>{t('SALIR', 'EXIT', '나가기')}</span>
              <div className={styles.price}>
                <span className={styles.priceAmount}>{t('0,9%', '0.9%', '0.9%')}</span>
                <span className={styles.pricePeriod}>{t('una sola vez al convertir', 'once when converting', '전환할 때 한 번')}</span>
              </div>
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Convierte de vuelta a USDT', 'Convert back to USDT', 'USDT로 다시 전환')}</h3>
              <p className={styles.cardText}>{t('Aplica al retirar a moneda local o enviar USDT a una billetera externa. Siempre ves el monto final antes de confirmar.', 'Applies when withdrawing to local currency or sending USDT to an external wallet. You always see the final amount before confirming.', '현지 통화로 출금하거나 외부 지갑으로 USDT를 보낼 때 적용됩니다. 확인 전에 항상 최종 금액을 볼 수 있습니다.')}</p>
              <div className={styles.example}>
                <span>{t('Conviertes', 'You convert', '전환 금액')} US$100</span>
                <span>{t('Comisión de Confío US$0,90', 'Confío fee US$0.90', 'Confío 수수료 US$0.90')}</span>
                <strong>{t('Recibes US$99,10', 'You receive US$99.10', 'US$99.10 수령')}</strong>
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
            <span className={styles.footerIcon} aria-hidden="true">💡</span>
            <div>
              <h4 className={styles.footerTitle}>{t('Una regla simple, sin planes ni membresías', 'One simple rule—no plans or memberships', '요금제나 멤버십 없는 하나의 간단한 규칙')}</h4>
              <p className={styles.footerText}>
                {t('Personas y negocios pagan lo mismo: 0,9% al entrar y 0,9% al salir del sistema de dólares de Confío. Enviar entre usuarios y convertir entre cUSD y cUSD+ cuesta 0%. Los pagos con Confío Pay tienen una comisión de 0,9%, mostrada antes de confirmar.', 'People and businesses pay the same: 0.9% when entering and 0.9% when leaving the Confío dollar system. Sending between users and moving between cUSD and cUSD+ costs 0%. Confío Pay payments carry a 0.9% fee, shown before confirmation.', '개인과 비즈니스 모두 동일하게 Confío 달러 시스템에 들어올 때 0.9%, 나갈 때 0.9%를 지불합니다. 사용자 간 송금과 cUSD·cUSD+ 전환은 0%입니다. Confío Pay 결제에는 확인 전에 표시되는 0.9% 수수료가 적용됩니다.')}
              </p>
              <p className={styles.providerNote}>
                {t('El 0,9% es la comisión de Confío. El tipo de cambio y cualquier cargo de un proveedor externo, si aplica, se muestran por separado antes de confirmar.', 'The 0.9% is Confío’s fee. The exchange rate and any third-party provider charge, if applicable, are shown separately before confirmation.', '0.9%는 Confío의 수수료입니다. 환율과 제3자 제공업체의 수수료가 있는 경우 확인 전에 별도로 표시됩니다.')}
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyFeeStructure;
