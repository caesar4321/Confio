import React from 'react';
import { Link } from 'react-router-dom';
import { useLanguage } from '../../contexts/LanguageContext';
import styles from '../../styles/FriendlyFooter.module.css';

const FriendlyFooter = () => {
  const { t } = useLanguage();
  
  return (
    <footer className={styles.footer}>
      <div className={styles.container}>
        <div className={styles.content}>
          <div className={styles.brand}>
            <h3 className={styles.logo}>Confío</h3>
            <p className={styles.tagline}>
              {t('Confío en vos.', 'We trust you.', '당신을 믿습니다.')}
            </p>
          </div>
          
          <div className={styles.links}>
            <h4 className={styles.linksTitle}>{t('Explorar', 'Explore', '탐색')}</h4>
            <a href="/discover/" className={styles.link}>
              {t('Descubrir', 'Discover', '발견하기')}
            </a>
            <Link to="/terms" className={styles.link}>
              {t('Términos de Servicio', 'Terms of Service', '서비스 약관')}
            </Link>
            <Link to="/privacy" className={styles.link}>
              {t('Política de Privacidad', 'Privacy Policy', '개인정보 보호정책')}
            </Link>
            <Link to="/deletion" className={styles.link}>
              {t('Eliminar Datos', 'Delete Data', '데이터 삭제')}
            </Link>
          </div>
          
          <div className={styles.links}>
            <h4 className={styles.linksTitle}>{t('Sobre', 'About', '소개')}</h4>
            <a href="/about/julian-moon/" className={styles.link}>
              {t('Julian Moon (Fundador)', 'Julian Moon (Founder)', 'Julian Moon (창업자)')}
            </a>
            <a href="/about/confio-news/" className={styles.link}>
              {t('Confío News', 'Confío News', 'Confío News')}
            </a>
          </div>

          <div className={styles.contact}>
            <h4 className={styles.contactTitle}>{t('Contacto', 'Contact', '연락처')}</h4>
            <a href="mailto:support@confio.lat" className={styles.email}>
              support@confio.lat
            </a>
          </div>
        </div>
        
        <div className={styles.bottom}>
          <p className={styles.copyright}>
            {t(
              'Confío es un servicio de Duende Limited, sociedad constituida en la República de Seychelles.',
              'Confío is a service of Duende Limited, a company incorporated in the Republic of Seychelles.',
              'Confío는 세이셸 공화국에 설립된 Duende Limited의 서비스입니다.'
            )}
            <br />
            Suite 102 Aarti Chambers, Mont Fleuri, Victoria, Mahé, Seychelles
          </p>
          <p className={styles.copyright}>
            © {new Date().getFullYear()} Duende Limited. {t('Todos los derechos reservados', 'All rights reserved', '모든 권리 보유')}
          </p>
        </div>
      </div>
    </footer>
  );
};

export default FriendlyFooter;