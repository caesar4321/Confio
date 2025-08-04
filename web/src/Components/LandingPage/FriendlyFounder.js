import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyFounder.module.css';
import julianImage from '../../images/JulianMoon_Founder.jpeg';
import tiktokIcon from '../../images/TikTok.png';
import instagramIcon from '../../images/Instagram.png';
import youtubeIcon from '../../images/YouTube.png';
import telegramIcon from '../../images/TelegramLogo.svg';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyFounder = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  return (
    <section className={styles.founder} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.content}
        >
          <div className={styles.imageContainer}>
            <img 
              src={julianImage} 
              alt="Julian Moon - Fundador de Confío" 
              className={styles.founderImage}
            />
            <div className={styles.imageBadge}>
              <span>🚀</span>
              <span>Fundador & CEO</span>
            </div>
          </div>

          <div className={styles.textContent}>
            <span className={styles.badge}>🌐 {t('VISIONARIO DE FINTECH LATAM', 'LATAM FINTECH VISIONARY', '라틴 아메리카 핀테크 비전가')}</span>
            <h2 className={styles.title}>
              {t('Hola, soy Julian Moon', 'Hi, I\'m Julian Moon', '안녕하세요, 줄리안 문입니다')}
              <span className={styles.highlight}> 🌙</span>
            </h2>
            
            <div className={styles.story}>
              <p>
                {t('Vine desde Corea a América Latina con una misión clara:', 'I came from Korea to Latin America with a clear mission:', '한국에서 라틴 아메리카로 명확한 사명을 가지고 왔습니다:')} <strong>{t('entender de cerca los desafíos financieros', 'understand financial challenges up close', '금융 문제를 가까이서 이해하기')}</strong> {t('que enfrentan millones de personas. No desde una oficina lejana, sino viviendo aquí, compartiendo las mismas experiencias.', 'that millions face. Not from a distant office, but living here, sharing the same experiences.', '수백만 명이 직면한 문제들. 멀리 떨어진 사무실이 아닌, 여기서 함께 살면서 같은 경험을 공유하며.')}
              </p>
              
              <p>
                {t('Cada día escucho historias de venezolanos separados de sus familias, argentinos protegiendo sus ahorros, bolivianos buscando estabilidad.', 'Every day I hear stories of Venezuelans separated from their families, Argentinians protecting their savings, Bolivians seeking stability.', '매일 가족과 떨어진 베네수엘라인, 저축을 지키는 아르헨티나인, 안정을 찾는 볼리비아인들의 이야기를 듣습니다.')} <strong>{t('Estas historias me motivan a trabajar más duro', 'These stories motivate me to work harder', '이런 이야기들이 저를 더 열심히 일하게 합니다')}</strong> {t('para crear la solución que todos necesitamos.', 'to create the solution we all need.', '우리 모두가 필요로 하는 솔루션을 만들기 위해.')}
              </p>

              <p>
                {t('Confío es más que una app. Es mi compromiso con cada latinoamericano:', 'Confío is more than an app. It\'s my commitment to every Latin American:', 'Confío는 단순한 앱이 아닙니다. 모든 라틴 아메리카인에 대한 저의 약속입니다:')} <strong>{t('todos merecemos herramientas financieras justas', 'we all deserve fair financial tools', '우리 모두는 공정한 금융 도구를 받을 자격이 있습니다')}</strong>. {t('Herramientas para proteger nuestro dinero, apoyar a nuestras familias, y construir un futuro más estable.', 'Tools to protect our money, support our families, and build a more stable future.', '우리의 돈을 보호하고, 가족을 지원하고, 더 안정적인 미래를 구축하기 위한 도구.')}
              </p>

              <p className={styles.quote}>
                {t('"Un coreano en LATAM creando soluciones con ustedes, no para ustedes. Juntos estamos construyendo algo especial."', '"A Korean in LATAM creating solutions with you, not for you. Together we\'re building something special."', '"라틴 아메리카에 있는 한국인으로서 여러분을 위해서가 아닌, 여러분과 함께 솔루션을 만들고 있습니다. 함께 특별한 것을 만들고 있습니다."')}
              </p>
            </div>

            <div className={styles.socialLinks}>
              <a href="https://tiktok.com/@julianmoonluna" target="_blank" rel="noopener noreferrer" className={styles.socialIconLink} title="TikTok">
                <img src={tiktokIcon} alt="TikTok" className={styles.socialIcon} />
              </a>
              <a href="https://instagram.com/julianmoonluna" target="_blank" rel="noopener noreferrer" className={styles.socialIconLink} title="Instagram">
                <img src={instagramIcon} alt="Instagram" className={styles.socialIcon} />
              </a>
              <a href="https://youtube.com/@julianmoonluna" target="_blank" rel="noopener noreferrer" className={styles.socialIconLink} title="YouTube">
                <img src={youtubeIcon} alt="YouTube" className={styles.socialIcon} />
              </a>
              <a href="https://t.me/FansDeJulian" target="_blank" rel="noopener noreferrer" className={styles.socialIconLink} title="Telegram">
                <img src={telegramIcon} alt="Telegram" className={styles.socialIcon} />
              </a>
            </div>

            <div className={styles.cta}>
              <p className={styles.ctaText}>
                {t('Únete a nuestra comunidad y sé parte del cambio', 'Join our community and be part of the change', '우리 커뮤니티에 참여하고 변화의 일부가 되세요')}
              </p>
              <button className={styles.ctaButton} onClick={() => window.open('https://t.me/FansDeJulian', '_blank')}>
                {t('Unirse al Grupo de Telegram', 'Join Telegram Group', '텔레그램 그룹 참여')}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyFounder;