import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyAssets.module.css';
import cUSDLogo from '../../images/cUSD.png';
import cUSDPlusLogo from '../../images/cUSDPlus.png';
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
        { label: t('Red', 'Network', '네트워크'), value: 'Algorand' },
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
      logo: cUSDPlusLogo,
      name: 'Confío Dollar+',
      symbol: '$cUSD+',
      color: '#10b981',
      comingSoon: t('Próximamente', 'Coming soon', '출시 예정'),
      details: [
        { label: t('¿Qué es?', 'What is it?', '무엇인가요?'), value: t('Tu ahorro en dólares que crece cada día, respaldado por USDY de Ondo Finance.', 'Your dollar savings growing every day, backed by Ondo Finance\'s USDY.', '매일 성장하는 달러 저축으로, Ondo Finance의 USDY로 담보됩니다.') },
        { label: t('Respaldado por', 'Backed by', '지원'), value: t('100% USDY (bonos del Tesoro de EE.UU. tokenizados)', '100% USDY (tokenized U.S. Treasury bonds)', '100% USDY (토큰화된 미국 국채)') },
        { label: t('Uso principal', 'Main use', '주요 용도'), value: t('Ahorro con rendimiento dentro de Confío.', 'Yield-bearing savings inside Confío.', 'Confío 안의 수익형 저축입니다.') },
        { label: t('Valor', 'Value', '가치'), value: t('Acumulativo — crece con el rendimiento', 'Accumulating — grows with the yield', '누적형 — 수익과 함께 성장') },
        { label: t('Red', 'Network', '네트워크'), value: 'BNB Smart Chain' },
        {
          label: t('Contrato', 'Contract', '컨트랙트'),
          value: (
            <a href="https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              0x3C29…3Ed1
            </a>
          )
        },
        {
          label: t('Explorador', 'Explorer', '탐색기'),
          value: (
            <a href="https://bscscan.com/token/0x3C29417eb4314155e63d4C7D4507852b87763Ed1" target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
              {t('Ver en BscScan', 'View on BscScan', 'BscScan에서 보기')}
            </a>
          )
        },
        { label: t('Estado', 'Status', '상태'), value: t('En preparación con Ondo Finance', 'In preparation with Ondo Finance', 'Ondo Finance와 준비 중') }
      ],
      highlight: {
        icon: '🌱',
        text: t('Confío Dollar+($cUSD+) llega pronto: ahorro respaldado por bonos del Tesoro de EE.UU., con reservas verificables en cadena.', 'Confío Dollar+($cUSD+) is coming soon: savings backed by U.S. Treasury bonds, with on-chain verifiable reserves.', 'Confío Dollar+($cUSD+)가 곧 출시됩니다: 미국 국채로 담보된 저축, 체인에서 검증 가능한 준비금.')
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
        { label: t('Red', 'Network', '네트워크'), value: 'Algorand' },
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
    <section className={styles.assets} ref={ref} id="activos">
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('NUESTROS ACTIVOS', 'OUR ASSETS', '우리의 자산')}</span>
          <h2 className={styles.title}>
            <span className={styles.highlight}>Confío Dollar($cUSD)</span>, <span className={styles.highlight2}>Confío($CONFIO)</span> {t('y tu ahorro', 'and your savings', '그리고 당신의 저축')} <span className={styles.highlight}>Confío Dollar+($cUSD+)</span>
          </h2>
          <p className={styles.subtitle}>
            {t('Dos monedas y un instrumento de ahorro, unidos por la misma misión', 'Two currencies and one savings instrument, united by the same mission', '두 개의 통화와 하나의 저축 상품, 같은 사명으로 하나됨')}
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
                  {asset.comingSoon && (
                    <span
                      style={{
                        display: 'inline-block',
                        marginTop: 4,
                        padding: '2px 10px',
                        borderRadius: 100,
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        color: '#10b981',
                        background: '#ecfdf5',
                      }}
                    >
                      {asset.comingSoon}
                    </span>
                  )}
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
          <a href={t('https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.es.md', 'https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.md', 'https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.ko.md')} target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📄</span>
            <span>{t('Whitepaper', 'Whitepaper', '백서')}</span>
          </a>
          <a href={t('https://github.com/caesar4321/Confio/blob/main/docs/tokenomics/README.es.md', 'https://github.com/caesar4321/Confio/blob/main/docs/tokenomics/README.md', 'https://github.com/caesar4321/Confio/blob/main/docs/tokenomics/README.ko.md')} target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
            <span className={styles.documentIcon}>📘</span>
            <span>{t('Tokenomics', 'Tokenomics', '토크노믹스')}</span>
          </a>
          <a href={t('https://github.com/caesar4321/Confio/blob/main/docs/pitchdeck/CONFIO_Presale_Deck_ES.pdf', 'https://github.com/caesar4321/Confio/blob/main/docs/pitchdeck/CONFIO_Presale_Deck_EN.pdf', 'https://github.com/caesar4321/Confio/blob/main/docs/pitchdeck/CONFIO_Presale_Deck_KO.pdf')} target="_blank" rel="noopener noreferrer" className={styles.documentLink}>
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
