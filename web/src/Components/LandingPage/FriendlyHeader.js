import React from 'react';
import styles from '../../styles/FriendlyHeader.module.css';
import confioLogo from '../../images/CONFIO.png';
import LanguageSwitcher from './LanguageSwitcher';
import { useLanguage } from '../../contexts/LanguageContext';

// Site header per DESIGN.md: brand lockup (mark + single-color wordmark),
// section anchors, language switcher, one download CTA.
const FriendlyHeader = () => {
  const { t } = useLanguage();

  return (
    <header className={styles.header}>
      <div className={styles.container}>
        <a href="/" className={styles.brand}>
          <img src={confioLogo} alt="" className={styles.logoMark} />
          <span className={styles.wordmark}>Confío</span>
        </a>

        <nav className={styles.nav} aria-label={t('Secciones', 'Sections', '섹션')}>
          <a href="#asi-funciona" className={styles.navLink}>
            {t('Cómo funciona', 'How it works', '작동 방식')}
          </a>
          <a href="#activos" className={styles.navLink}>
            {t('Activos', 'Assets', '자산')}
          </a>
          <a
            href="https://github.com/caesar4321/Confio"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.navLink}
          >
            {t('Código abierto', 'Open source', '오픈 소스')}
          </a>
        </nav>

        <div className={styles.actions}>
          <LanguageSwitcher />
          <a
            href="https://confio.lat/invite/JULIANMOONLUNA?utm_source=confio.lat&utm_medium=web&utm_campaign=landing_header"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.cta}
          >
            {t('Descargar', 'Download', '다운로드')}
          </a>
        </div>
      </div>
    </header>
  );
};

export default FriendlyHeader;
