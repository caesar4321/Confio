import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@apollo/client';
import styles from '../../styles/FriendlyHeroSection.module.css';
import confioHomeDemo from '../../images/ConfioHomeDemo.jpeg';
import { useLanguage } from '../../contexts/LanguageContext';
import { LANDING_STATS, toStatValue } from './landingStats';
import TickerNumber from './TickerNumber';

// «Radicalmente Normal» hero (DESIGN.md): calm declarative headline,
// the real app as the only hero image, live traction with tick-settle.
const FriendlyHeroSection = ({ title, subtitle, showDownloadButtons = true }) => {
  const { t } = useLanguage();

  const { data: statsData } = useQuery(LANDING_STATS, { fetchPolicy: 'cache-and-network' });
  const live = statsData?.landingStats;
  // Live values only — no hardcoded fallbacks (DESIGN.md: real numbers or
  // nothing). Whole dollars only (floored, never rounded up): decimals
  // reintroduce the "," vs "." ambiguity across LATAM locales, and a money
  // site must not advertise more than reality. Zero/NaN don't render.
  const deposited = toStatValue(live?.depositedVolumeUsd);
  const presale = toStatValue(live?.presaleRaisedUsd);

  const defaultTitle = (
    <>
      {t('Dólares.', 'Dollars.', '달러를,')}
      <br />
      <span className={styles.highlight}>{t('Así de simple.', 'This simple.', '이렇게 간단하게.')}</span>
    </>
  );

  const defaultSubtitle = t(
    'Envía, paga, ahorra e invierte dólares digitales desde tu celular. Sin banco, sin comisiones de red, sin complicaciones.',
    'Send, pay, save and invest digital dollars from your phone. No bank, no network fees, no complications.',
    '휴대폰으로 디지털 달러를 보내고, 결제하고, 저축하고, 투자하세요. 은행 없이, 네트워크 수수료 없이, 복잡함 없이.'
  );

  return (
    <section className={styles.hero}>
      <div className={styles.container}>
        <div className={styles.heroContent}>
          {/* Left — the calm claim */}
          <div className={styles.contentSide}>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.05 }}
              className={styles.title}
            >
              {title || defaultTitle}
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.15 }}
              className={styles.subtitle}
            >
              {subtitle || defaultSubtitle}
            </motion.p>

            {showDownloadButtons && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.25 }}
                className={styles.ctaButtons}
              >
                <a
                  href="https://play.google.com/store/apps/details?id=com.Confio.Confio"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.storeButton}
                >
                  <img
                    src="https://upload.wikimedia.org/wikipedia/commons/7/78/Google_Play_Store_badge_EN.svg"
                    alt="Get it on Google Play"
                    className={styles.storeBadge}
                  />
                </a>
                <a
                  href="https://apps.apple.com/app/id6472662314"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.storeButton}
                >
                  <img
                    src="https://upload.wikimedia.org/wikipedia/commons/3/3c/Download_on_the_App_Store_Badge.svg"
                    alt="Download on the App Store"
                    className={styles.storeBadge}
                  />
                </a>
              </motion.div>
            )}

            {/* Live traction — real numbers styled like app balances */}
            {!title && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.35 }}
                className={styles.statRow}
              >
                {deposited != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={deposited} className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('depositados on-chain', 'deposited on-chain', '온체인 입금 총액')}
                    </span>
                  </div>
                )}
                {presale != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={presale} className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('recaudados en preventa', 'raised in presale', '프리세일 모금액')}
                    </span>
                  </div>
                )}
                <div className={styles.statBlock}>
                  <span className={styles.statValue}>US$0.00</span>
                  <span className={styles.statLabel}>
                    {t('comisión de red, siempre', 'network fees, always', '네트워크 수수료, 항상')}
                  </span>
                </div>
              </motion.div>
            )}
          </div>

          {/* Right — the real app, nothing else */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className={styles.phoneSide}
          >
            <div className={styles.phoneBackdrop} aria-hidden="true" />
            <div className={styles.phoneFrame}>
              <img
                src={confioHomeDemo}
                alt={t(
                  'App Confío — pantalla de inicio real',
                  'Confío app — real home screen',
                  'Confío 앱 — 실제 홈 화면'
                )}
                className={styles.phoneShot}
                width={640}
                height={1422}
                fetchpriority="high"
              />
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
};

export default FriendlyHeroSection;
