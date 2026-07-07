import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import styles from '../../styles/FriendlyHeroSection.module.css';
import confioLogo from '../../images/CONFIO.png';
import confioAppMockup from '../../images/ConfioApp.png';
import cUSDLogo from '../../images/cUSD.png';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyHeroSection = ({ title, subtitle, showDownloadButtons = true }) => {
  const [currentTestimonial, setCurrentTestimonial] = useState(0);
  const { t } = useLanguage();

  const miniTestimonials = [
    {
      name: 'María',
      country: '🇻🇪',
      text: t('Envío dinero a mi familia sin complicaciones', 'I send money to my family without complications', '가족에게 복잡함 없이 돈을 보내요')
    },
    {
      name: 'Carlos',
      country: '🇦🇷',
      text: t('Protejo mis ahorros de la inflación', 'I protect my savings from inflation', '인플레이션으로부터 저축을 보호해요')
    },
    {
      name: 'Ana',
      country: '🇲🇽',
      text: t('Recibo pagos de mis clientes al instante', 'I receive payments from my clients instantly', '고객으로부터 즉시 결제를 받아요')
    }
  ];

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTestimonial((prev) => (prev + 1) % miniTestimonials.length);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Default content if no props are provided
  const defaultTitle = (
    <>
      {t('Tu dinero en dólares,', 'Your money in dollars,', '당신의 돈을 달러로,')}
      <span className={styles.highlight}> {t('simple y seguro', 'simple and secure', '간단하고 안전하게')}</span>
    </>
  );

  const defaultSubtitle = t(
    'Envía, recibe y ahorra dólares digitales desde tu celular. Sin cuentas bancarias, sin complicaciones.',
    'Send, receive and save digital dollars from your phone. No bank accounts, no complications.',
    '휴대폰으로 디지털 달러를 보내고, 받고, 저축하세요. 은행 계좌 없이, 복잡함 없이.'
  );

  return (
    <section className={styles.hero}>
      {/* Friendly gradient background */}
      <div className={styles.backgroundPattern}>
        <div className={styles.gradientCircle1} />
        <div className={styles.gradientCircle2} />
        <div className={styles.floatingMoney}>💵</div>
        <div className={styles.floatingHeart}>💚</div>
        <div className={styles.floatingGlobe}>🌎</div>
      </div>

      <div className={styles.container}>
        <div className={styles.heroContent}>
          {/* Left side - Content */}
          <div className={styles.contentSide}>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.1 }}
              className={styles.title}
            >
              {title || defaultTitle}
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.2 }}
              className={styles.subtitle}
            >
              {subtitle || defaultSubtitle}
            </motion.p>

            {/* Benefits list - Only show on main landing (when no custom title) */}
            {!title && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.3 }}
                className={styles.benefits}
              >
                <div className={styles.benefit}>
                  <span className={styles.checkIcon}>✓</span>
                  <span>{t('Sin comisiones ocultas', 'No hidden fees', '숨겨진 수수료 없음')}</span>
                </div>
                <div className={styles.benefit}>
                  <span className={styles.checkIcon}>✓</span>
                  <span>{t('Registro en 30 segundos', 'Sign up in 30 seconds', '30초 만에 가입')}</span>
                </div>
                <div className={styles.benefit}>
                  <span className={styles.checkIcon}>✓</span>
                  <span>{t('Protegido contra inflación', 'Protected against inflation', '인플레이션으로부터 보호')}</span>
                </div>
              </motion.div>
            )}

            {/* App Store Buttons */}
            {showDownloadButtons && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.4 }}
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

            {/* Mini testimonials - Only show on main landing */}
            {!title && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6, delay: 0.5 }}
                className={styles.miniTestimonials}
              >
                <div className={styles.avatars}>
                  <div className={styles.avatar}>👩</div>
                  <div className={styles.avatar}>👨</div>
                  <div className={styles.avatar}>👩</div>
                  <div className={styles.avatarMore}>+7000</div>
                </div>
                <div className={styles.testimonialText}>
                  <p>
                    <strong>{miniTestimonials[currentTestimonial].name}</strong> de {miniTestimonials[currentTestimonial].country}:
                    "{miniTestimonials[currentTestimonial].text}"
                  </p>
                </div>
              </motion.div>
            )}
          </div>

          {/* Right side - Real App Mockup */}
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8, delay: 0.3 }}
            className={styles.phoneSide}
          >
            <div className={styles.phoneContainer}>
              <img
                src={confioAppMockup}
                alt="Confío App"
                className={styles.appMockup}
              />

              {/* Floating elements around mockup - Only show on main landing, or minimal version */}
              {!title && (
                <>
                  <div className={styles.floatingCard}>
                    <img src={confioLogo} alt="Confío" className={styles.floatingLogo} />
                    <span>{t('¡Transferencia exitosa!', 'Transfer successful!')}</span>
                  </div>

                  <div className={styles.floatingBadge}>
                    <img src={cUSDLogo} alt="cUSD" className={styles.floatingCusd} />
                    <span>{t('Dólares digitales', 'Digital dollars')}</span>
                  </div>

                  <div className={styles.floatingStats}>
                    <span className={styles.statsIcon}>📈</span>
                    <span>{t('Más de 7.000 usuarios en LATAM', 'Over 7,000 users across LATAM')}</span>
                  </div>
                </>
              )}
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
};

export default FriendlyHeroSection;
