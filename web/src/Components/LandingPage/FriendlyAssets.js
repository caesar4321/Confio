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
        { label: t('¿Qué es?', 'What is it?', '무엇인가요?'), value: t('Stablecoin 1:1 respaldada por USDC.', '1:1 stablecoin backed by USDC.', 'USDC로 1:1 담보된 스테이블코인입니다.') },
        { label: t('Respaldado por', 'Backed by', '지원'), value: '100% USDC' },
        { label: t('Uso principal', 'Main use', '주요 용도'), value: t('Medio de pago y ahorro dentro del ecosistema Confío.', 'Payment and savings rail inside the Confío ecosystem.', 'Confío 생태계에서 결제 및 저축 수단으로 사용됩니다.') },
        { label: t('Valor', 'Value', '가치'), value: t('Estable (1:1 con USDC)', 'Stable (1:1 with USDC)', '안정적 (USDC와 1:1)') },
        {
          label: t('ID del Activo', 'Asset ID', '자산 ID'),
          value: (
            <a href="https://explorer.perawallet.app/asset/3198259450/" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              3198259450
            </a>
          )
        },
        {
          label: t('Explorador', 'Explorer', '탐색기'),
          value: (
            <a href="https://explorer.perawallet.app/asset/3198259450/" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              {t('Ver en Pera Explorer', 'View on Pera Explorer', 'Pera Explorer에서 보기')}
            </a>
          )
        }
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
        { label: t('¿Qué es?', 'What is it?', '무엇인가요?'), value: t('Token de gobernanza, recompensas y preventa.', 'Governance, rewards and presale token.', '거버넌스, 리워드 및 프리세일 토큰입니다.') },
        { label: t('Respaldado por', 'Backed by', '지원'), value: t('Confianza y participación de la comunidad Confío.', 'Trust and participation from the Confío community.', 'Confío 커뮤니티의 신뢰와 참여.') },
        { label: t('Uso principal', 'Main use', '주요 용도'), value: t('Refleja la participación y beneficios dentro de Confío.', 'Reflects engagement and benefits inside Confío.', 'Confío 내 참여와 혜택을 반영합니다.') },
        { label: t('Valor', 'Value', '가치'), value: t('Variable', 'Variable', '변동') },
        {
          label: t('ID del Activo', 'Asset ID', '자산 ID'),
          value: (
            <a href="https://explorer.perawallet.app/asset/3351104258/" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              3351104258
            </a>
          )
        },
        {
          label: t('Explorador', 'Explorer', '탐색기'),
          value: (
            <a href="https://explorer.perawallet.app/asset/3351104258/" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              {t('Ver en Pera Explorer', 'View on Pera Explorer', 'Pera Explorer에서 보기')}
            </a>
          )
        }
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
          <a href={t('https://medium.com/confio4world/la-visión-de-confío-db2416ae3025', 'https://medium.com/confio4world/duende-cryptocurrency-and-its-exclusive-payment-platform-to-facilitate-cryptocurrency-mass-c0a7499d0e81', 'https://medium.com/confio4world/confío-중남미를-위한-디지털-달러-플랫폼-570adde1dfe3')} target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📄</span>
            <span>{t('Whitepaper', 'Whitepaper', '백서')}</span>
          </a>
          <a href="https://medium.com/confio4world/tokenomics-oficial-de-confío-versión-2025-comunidad-latam-152815f9bcc9" target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📘</span>
            <span>{t('Tokenomics 2025 (ES)', 'Tokenomics 2025 (ES)', '토크노믹스 2025 (ES)')}</span>
          </a>
          <a href="https://medium.com/confio4world/confío-official-tokenomics-2025-english-edition-421a310a18fb" target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📗</span>
            <span>{t('Tokenomics 2025 (EN)', 'Tokenomics 2025 (EN)', '토크노믹스 2025 (EN)')}</span>
          </a>
          <a href={t('https://docs.google.com/presentation/d/157hcgmSUkaDmBzyvo_LJZKTU0s9D7SjW/edit?usp=sharing&ouid=118055710232569593824&rtpof=true&sd=true', 'https://docs.google.com/presentation/d/1HCW8mBXMpYhT2m48xg9141nkaqLmGARo/edit?usp=sharing&ouid=104671499626663887236&rtpof=true&sd=true', 'https://docs.google.com/presentation/d/1HCW8mBXMpYhT2m48xg9141nkaqLmGARo/edit?usp=sharing&ouid=104671499626663887236&rtpof=true&sd=true')} target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📊</span>
            <span>{t('Presentación de Confío', 'Pitch Deck', '피치덱')}</span>
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
