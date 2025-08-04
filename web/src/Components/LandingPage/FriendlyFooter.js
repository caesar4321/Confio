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
              {t('Tu dinero digital, simple y seguro', 'Your digital money, simple and secure', '당신의 디지털 머니, 간단하고 안전하게')}
            </p>
          </div>
          
          <div className={styles.links}>
            <h4 className={styles.linksTitle}>{t('Legal', 'Legal', '법률')}</h4>
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
          
          <div className={styles.contact}>
            <h4 className={styles.contactTitle}>{t('Contacto', 'Contact', '연락처')}</h4>
            <a href="mailto:support@confio.lat" className={styles.email}>
              support@confio.lat
            </a>
          </div>
        </div>
        
        <div className={styles.bottom}>
          <p className={styles.copyright}>
            © 2025 Confío. {t('Todos los derechos reservados', 'All rights reserved', '모든 권리 보유')}
          </p>
        </div>
      </div>
    </footer>
  );
};

export default FriendlyFooter;