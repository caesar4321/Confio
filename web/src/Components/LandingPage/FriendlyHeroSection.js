import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@apollo/client';
import styles from '../../styles/FriendlyHeroSection.module.css';
import confioHomeDemo from '../../images/screens/pedile.jpg';
import { useLanguage } from '../../contexts/LanguageContext';
import {
  FUND_FLOW_STATS, INVEST_TRADED_USD, LANDING_STATS, RESERVE_STATS, reserveTotal, toStatValue,
} from './landingStats';
import TickerNumber from './TickerNumber';

// «Radicalmente Normal» hero (DESIGN.md): calm declarative headline,
// the app as the only hero image, live traction with tick-settle. Since
// 5.4.0 the app's Inicio is the conversation, so the claim is what you can
// ask for, and the screen is the chat.
const FriendlyHeroSection = ({ title, subtitle, showDownloadButtons = true }) => {
  const { t } = useLanguage();

  const { data: statsData } = useQuery(LANDING_STATS, { fetchPolicy: 'cache-and-network' });
  const { data: flowData } = useQuery(FUND_FLOW_STATS, { fetchPolicy: 'cache-and-network' });
  const { data: reserveData } = useQuery(RESERVE_STATS, { fetchPolicy: 'cache-and-network' });
  const { data: investData } = useQuery(INVEST_TRADED_USD, { fetchPolicy: 'cache-and-network' });
  const live = statsData?.landingStats;
  // Live values only — no hardcoded fallbacks (DESIGN.md: real numbers or
  // nothing). Whole dollars only (floored, never rounded up): decimals
  // reintroduce the "," vs "." ambiguity across LATAM locales, and a money
  // site must not advertise more than reality. Zero/NaN don't render.
  // Deposits AND withdrawals: money that gets out is the proof LATAM users
  // look for, and the figure no longer shrinks when a large holder leaves.
  const moved = toStatValue(flowData?.fundFlowStats?.totalUsd);
  const reserves = toStatValue(reserveTotal(reserveData?.statsSummary));
  const traded = toStatValue(investData?.investTradedUsd);
  const presale = toStatValue(live?.presaleRaisedUsd);
  const registeredUsers = toStatValue(live?.registeredUsers);

  const defaultTitle = (
    <>
      {t('Pedíselo', 'Just ask.', '말만 하세요.')}
      <br />
      <span className={styles.highlight}>{t('y listo.', 'It’s done.', '그럼 끝.')}</span>
    </>
  );

  const defaultSubtitle = t(
    'Escribile a Confío lo que necesitás, como a una persona: mandar plata a tu familia, comprar acciones de EE.UU., hacer una compra o responder tu WhatsApp. Vos aprobás cada paso.',
    'Tell Confío what you need, the way you’d text a person: send money to your family, buy U.S. stocks, shop online or answer your WhatsApp. You approve every step.',
    '사람에게 말하듯 Confío에게 필요한 것을 적어 보세요. 가족에게 송금, 미국 주식 매수, 온라인 쇼핑, WhatsApp 답장까지. 모든 단계는 당신이 승인합니다.'
  );

  return (
    <section className={styles.hero}>
      <div className={styles.container}>
        <div className={styles.heroContent}>
          {/* Left — the calm claim */}
          <div className={styles.contentSide}>
            {!title && (
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className={styles.kicker}
              >
                {t('Confío en vos.', 'We trust you.', '당신을 믿습니다.')}
              </motion.p>
            )}
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
            {!title && [moved, reserves, traded, presale, registeredUsers].some((v) => v != null) && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.35 }}
                className={styles.statRow}
              >
                {moved != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={moved} className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('movidos en depósitos y retiros', 'moved in deposits and withdrawals', '입출금 총액')}
                    </span>
                  </div>
                )}
                {reserves != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={reserves} className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('en reservas de los dólares de Confío', 'in reserves backing Confío dollars', 'Confío 달러 준비금')}
                    </span>
                  </div>
                )}
                {traded != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={traded} className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('operados en inversiones', 'traded in investments', '투자 거래액')}
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
                {registeredUsers != null && (
                  <div className={styles.statBlock}>
                    <TickerNumber value={registeredUsers} prefix="" className={styles.statValue} />
                    <span className={styles.statLabel}>
                      {t('usuarios registrados', 'registered users', '등록 사용자')}
                    </span>
                  </div>
                )}
              </motion.div>
            )}
          </div>

          {/* Right — the app's conversation, nothing else */}
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
                  'App Confío — Inicio: la conversación, con ejemplos de lo que podés pedir',
                  'Confío app — Home: the conversation, with examples of what you can ask for',
                  'Confío 앱 — 홈: 대화 화면과 요청 예시'
                )}
                className={styles.phoneShot}
                width={600}
                height={1300}
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
