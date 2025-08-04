import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyAssets.module.css';
import cUSDLogo from '../../images/cUSD.png';
import confioLogo from '../../images/CONFIO.png';
import { useLanguage } from '../../contexts/LanguageContext';

const FriendlyAssets = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  const { t } = useLanguage();

  const assets = [
    {
      logo: cUSDLogo,
      name: 'Confío Dollar',
      symbol: '$cUSD',
      color: '#34d399',
      details: [
        { label: t('¿Qué es?', 'What is it?', '무엇인가요?'), value: t('Dólar digital estable', 'Stable digital dollar', '안정적인 디지털 달러') },
        { label: t('Respaldado por', 'Backed by', '지원'), value: '100% USDC' },
        { label: t('Uso principal', 'Main use', '주요 용도'), value: t('Envíos, pagos, ahorro', 'Transfers, payments, savings', '송금, 결제, 저축') },
        { label: t('Valor', 'Value', '가치'), value: t('Estable (1:1 con USDC)', 'Stable (1:1 with USDC)', '안정적 (USDC와 1:1)') }
      ],
      highlight: {
        icon: '🛡',
        text: t('Confío Dollar($cUSD) está respaldado 100% por USDC, el dólar digital más confiable del mundo.', 'Confío Dollar($cUSD) is 100% backed by USDC, the world\'s most reliable digital dollar.', 'Confío Dollar($cUSD)는 세계에서 가장 신뢰할 수 있는 디지털 달러인 USDC로 100% 지원됩니다.')
      }
    },
    {
      logo: confioLogo,
      name: 'Confío',
      symbol: '$CONFIO',
      color: '#8b5cf6',
      details: [
        { label: t('¿Qué es?', 'What is it?', '무엇인가요?'), value: t('Token de la comunidad', 'Community token', '커뮤니티 토큰') },
        { label: t('Respaldado por', 'Backed by', '지원'), value: t('Confianza, utilidad, futuro', 'Trust, utility, future', '신뢰, 유용성, 미래') },
        { label: t('Uso principal', 'Main use', '주요 용도'), value: t('Recompensas, misiones, beneficios', 'Rewards, missions, benefits', '보상, 미션, 혜택') },
        { label: t('Valor', 'Value', '가치'), value: t('Variable', 'Variable', '변동') }
      ],
      highlight: {
        icon: '💡',
        text: t('Confío($CONFIO) es para quienes creen en el futuro de esta comunidad.', 'Confío($CONFIO) is for those who believe in the future of this community.', 'Confío($CONFIO)는 이 커뮤니티의 미래를 믿는 사람들을 위한 것입니다.')
      }
    }
  ];

  return (
    <section className={styles.assets} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>💎 {t('NUESTRAS MONEDAS', 'OUR CURRENCIES', '우리의 통화')}</span>
          <h2 className={styles.title}>
            {t('Nuestras monedas: ', 'Our currencies: ', '우리의 통화: ')}<span className={styles.highlight}>Confío Dollar($cUSD)</span> {t('y', 'and', '그리고')} <span className={styles.highlight2}>Confío($CONFIO)</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Dos monedas digitales con propósitos diferentes, unidas por la misma misión', 'Two digital currencies with different purposes, united by the same mission', '다른 목적을 가진 두 개의 디지털 통화, 같은 사명으로 하나됨')}
          </p>
        </motion.div>

        <div className={styles.assetsGrid}>
          {assets.map((asset, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.2 * index }}
              className={styles.assetCard}
              style={{ borderColor: asset.color }}
            >
              <div className={styles.assetHeader}>
                <img src={asset.logo} alt={asset.name} className={styles.assetLogo} />
                <div className={styles.assetTitle}>
                  <h3 className={styles.assetName}>{asset.name}({asset.symbol})</h3>
                </div>
              </div>

              <div className={styles.assetDetails}>
                {asset.details.map((detail, idx) => (
                  <div key={idx} className={styles.detailRow}>
                    <span className={styles.detailLabel}>{detail.label}</span>
                    <span className={styles.detailValue}>{detail.value}</span>
                  </div>
                ))}
              </div>

              <div className={styles.assetHighlight} style={{ backgroundColor: `${asset.color}10`, borderColor: asset.color }}>
                <span className={styles.highlightIcon}>{asset.highlight.icon}</span>
                <p className={styles.highlightText}>{asset.highlight.text}</p>
              </div>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.5 }}
          className={styles.documents}
        >
          <a href="https://medium.com/confio4world/duende-cryptocurrency-and-its-exclusive-payment-platform-to-facilitate-cryptocurrency-mass-c0a7499d0e81" target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📄</span>
            <span>Whitepaper</span>
          </a>
          <a href="https://docs.google.com/presentation/d/1wRK7VE90fOZT8rqx2My61GKYJt7SPtum9ZMO2F1CK1Q/edit?usp=sharing" target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📊</span>
            <span>Pitchdeck</span>
          </a>
          <a href="https://github.com/caesar4321/Confio" target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>💻</span>
            <span>GitHub</span>
          </a>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyAssets;