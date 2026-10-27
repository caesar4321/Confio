import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import { useQuery } from '@apollo/client';
import styles from '../../styles/FriendlyFeeStructure.module.css';
import { useLanguage } from '../../contexts/LanguageContext';
import { PUBLIC_FEES, fmtBpsPct, fmtCents, toBps } from './landingStats';

const EXAMPLE_USD = 100;

const FriendlyFeeStructure = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t, language } = useLanguage();

  // Server-quoted only (DESIGN.md). Without live data the figures and
  // examples don't render; the rules around them still read correctly.
  const { data } = useQuery(PUBLIC_FEES, { fetchPolicy: 'cache-and-network' });
  const conversionBps = toBps(data?.publicFees?.conversionFeeBps);
  const payBps = toBps(data?.publicFees?.payFeeBps);
  const decimal = language === 'es' ? ',' : '.';
  const conversion = conversionBps != null ? fmtBpsPct(conversionBps, decimal) : null;
  const pay = payBps != null ? fmtBpsPct(payBps, decimal) : null;
  const exampleFee = conversionBps != null ? (EXAMPLE_USD * conversionBps) / 10000 : null;

  const price = conversion && (
    <div className={styles.price}>
      <span className={styles.priceAmount}>{conversion}</span>
      <span className={styles.pricePeriod}>{t('una sola vez al convertir', 'once when converting', '전환할 때 한 번')}</span>
    </div>
  );

  const example = exampleFee != null && (
    <div className={styles.example}>
      <span>{t('Convertís', 'You convert', '전환 금액')} US${EXAMPLE_USD}</span>
      <span>{t('Comisión de Confío', 'Confío fee', 'Confío 수수료')} {fmtCents(exampleFee, decimal)}</span>
      <strong>{t('Recibís', 'You receive', '수령')} {fmtCents(EXAMPLE_USD - exampleFee, decimal)}</strong>
    </div>
  );

  const summary = conversion && pay
    ? t(
        `Personas y negocios pagan lo mismo: ${conversion} al entrar y ${conversion} al salir del sistema de dólares de Confío. Enviar entre usuarios cuesta 0%. Los pagos con Confío Pay tienen una comisión de ${pay}, mostrada antes de confirmar.`,
        `People and businesses pay the same: ${conversion} when entering and ${conversion} when leaving the Confío dollar system. Sending between users costs 0%. Confío Pay payments carry a ${pay} fee, shown before confirmation.`,
        `개인과 비즈니스 모두 동일하게 Confío 달러 시스템에 들어올 때 ${conversion}, 나갈 때 ${conversion}를 지불합니다. 사용자 간 송금은 0%입니다. Confío Pay 결제에는 확인 전에 표시되는 ${pay} 수수료가 적용됩니다.`
      )
    : t(
        'Personas y negocios pagan la misma comisión al entrar y al salir del sistema de dólares de Confío. Enviar entre usuarios cuesta 0%. Los pagos con Confío Pay tienen su propia comisión, mostrada antes de confirmar.',
        'People and businesses pay the same fee when entering and leaving the Confío dollar system. Sending between users costs 0%. Confío Pay payments carry their own fee, shown before confirmation.',
        '개인과 비즈니스 모두 Confío 달러 시스템에 들어오고 나갈 때 같은 수수료를 지불합니다. 사용자 간 송금은 0%입니다. Confío Pay 결제에는 확인 전에 표시되는 별도 수수료가 적용됩니다.'
      );

  const providerNote = conversion
    ? t(
        `El ${conversion} es la comisión de Confío. El tipo de cambio y cualquier cargo de un proveedor externo, si aplica, se muestran por separado antes de confirmar.`,
        `The ${conversion} is Confío’s fee. The exchange rate and any third-party provider charge, if applicable, are shown separately before confirmation.`,
        `${conversion}는 Confío의 수수료입니다. 환율과 제3자 제공업체의 수수료가 있는 경우 확인 전에 별도로 표시됩니다.`
      )
    : t(
        'La comisión de Confío, el tipo de cambio y cualquier cargo de un proveedor externo, si aplica, se muestran por separado antes de confirmar.',
        'Confío’s fee, the exchange rate and any third-party provider charge, if applicable, are shown separately before confirmation.',
        'Confío의 수수료, 환율, 제3자 제공업체의 수수료가 있는 경우 확인 전에 별도로 표시됩니다.'
      );

  return (
    <section className={styles.feeStructure} ref={ref} id="tarifas">
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
            {t('Sin letra pequeña, sin sorpresas. Esto es lo que pagás.', 'No fine print, no surprises. This is what you pay.', '작은 글씨 없음, 놀라움 없음. 이것이 당신이 지불하는 것입니다.')}
          </p>
        </motion.div>

        <div className={styles.journeyIntro}>
          <span className={styles.journeyPill}>
            {t('La misma comisión de conversión para personas y negocios', 'The same conversion fee for people and businesses', '개인과 비즈니스 모두 동일한 전환 수수료')}
          </span>
          <p>
            {t('La comisión de conversión solo aplica al entrar o salir. Dentro de Confío, enviar entre usuarios es gratis; Confío Pay se cobra por separado.', 'The conversion fee only applies when entering or leaving. Inside Confío, sending between users is free; Confío Pay is priced separately.', '전환 수수료는 들어오거나 나갈 때만 적용됩니다. Confío 안에서 사용자 간 송금은 무료이며, Confío Pay는 별도로 부과됩니다.')}
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
              {price}
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Convertí a dólares de Confío', 'Convert into Confío dollars', 'Confío 달러로 전환')}</h3>
              <p className={styles.cardText}>{t('Aplica al entrar desde moneda local o desde USDT, tanto para personas como para negocios.', 'Applies when entering from local currency or USDT, for both people and businesses.', '현지 통화 또는 USDT로 들어올 때 개인과 비즈니스 모두에게 적용됩니다.')}</p>
              {example}
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
              {price}
            </div>
            <div className={styles.cardBody}>
              <h3 className={styles.cardTitle}>{t('Convertí de vuelta a USDT', 'Convert back to USDT', 'USDT로 다시 전환')}</h3>
              <p className={styles.cardText}>{t('Aplica al retirar a moneda local o enviar USDT a una billetera externa. Siempre ves el monto final antes de confirmar.', 'Applies when withdrawing to local currency or sending USDT to an external wallet. You always see the final amount before confirming.', '현지 통화로 출금하거나 외부 지갑으로 USDT를 보낼 때 적용됩니다. 확인 전에 항상 최종 금액을 볼 수 있습니다.')}</p>
              {example}
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
              <p className={styles.footerText}>{summary}</p>
              <p className={styles.providerNote}>{providerNote}</p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyFeeStructure;
