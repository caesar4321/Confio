import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyProducts.module.css';
import { useLanguage } from '../../contexts/LanguageContext';
import recibirShot from '../../images/screens/recibir.jpg';
import nvdaShot from '../../images/screens/nvda.jpg';
import futuroShot from '../../images/screens/tsla_posicion.jpg';
import comprarShot from '../../images/screens/comprar_producto.jpg';
import ligaShot from '../../images/screens/liga.jpg';

// One row per product, in the store listing's order, each with the real
// screen (DESIGN.md: product is the proof). Names and amounts in the
// screens are example data, never a member's.
const ProductRow = ({ product, index }) => {
  const [ref, inView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const reversed = index % 2 === 1;

  return (
    <article
      ref={ref}
      id={product.id}
      className={`${styles.row} ${reversed ? styles.rowReversed : ''}`}
    >
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.5 }}
        className={styles.copy}
      >
        <span className={styles.kicker}>{product.kicker}</span>
        <h3 className={styles.rowTitle}>{product.title}</h3>
        <p className={styles.rowBody}>{product.body}</p>
        <ul className={styles.points}>
          {product.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        {product.note && (
          <p className={`${styles.note} ${product.noteTone === 'risk' ? styles.noteRisk : ''}`}>
            {product.note}
          </p>
        )}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 32 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, delay: 0.1 }}
        className={styles.visual}
      >
        <div className={styles.backdrop} aria-hidden="true" />
        <div className={styles.phoneFrame}>
          <img
            src={product.shot}
            alt={product.alt}
            className={styles.phoneShot}
            width={600}
            height={product.shotHeight || 1206}
            loading="lazy"
            decoding="async"
          />
        </div>
      </motion.div>
    </article>
  );
};

const FriendlyProducts = () => {
  const [ref, inView] = useInView({ triggerOnce: true, threshold: 0.1 });
  const { t } = useLanguage();

  const products = [
    {
      id: 'enviar',
      kicker: t('ENVIÁ Y RECIBÍ', 'SEND AND RECEIVE', '보내기와 받기'),
      title: t('Dólares que llegan en segundos', 'Dollars that arrive in seconds', '몇 초 만에 도착하는 달러'),
      body: t(
        'Enviá dólares a otras personas, aunque vivan en otro país. Recargá desde tu banco o billetera, y pagá o cobrá con el QR de Confío.',
        'Send dollars to other people, even in another country. Top up from your bank or wallet, and pay or get paid with the Confío QR.',
        '다른 나라에 사는 사람에게도 달러를 보내세요. 은행이나 지갑에서 충전하고, Confío QR로 결제하거나 받으세요.'
      ),
      points: [
        t('Pix, Bre-B, CLABE, Pago Móvil y más países', 'Pix, Bre-B, CLABE, Pago Móvil and more countries', 'Pix, Bre-B, CLABE, Pago Móvil 등 여러 나라'),
        t('Recibí USDT desde otra billetera', 'Receive USDT from another wallet', '다른 지갑에서 USDT 받기'),
        t('Efectivo con un agente: financieras locales verificadas cerca de vos', 'Cash with an agent: verified local financial businesses near you', '현금은 에이전트와: 가까운 검증된 현지 금융업체'),
      ],
      shot: recibirShot,
      alt: t('App Confío — pantalla Recibir', 'Confío app — Receive screen', 'Confío 앱 — 받기 화면'),
    },
    {
      id: 'invertir',
      kicker: t('INVERTÍ', 'INVEST', '투자하기'),
      title: t('Acciones de EE.UU., desde tus dólares', 'U.S. stocks, from your dollars', '내 달러로 미국 주식'),
      body: t(
        'Invertí con poco en acciones digitales de Tesla, NVIDIA y más, emitidas por Ondo Stocks. Cada una sigue el precio de su acción. También oro y Bitcoin, las 24 horas.',
        'Invest small amounts in digital shares of Tesla, NVIDIA and more, issued by Ondo Stocks. Each one tracks its stock’s price. Gold and Bitcoin too, 24 hours a day.',
        'Ondo Stocks가 발행한 Tesla, NVIDIA 등의 디지털 주식에 소액으로 투자하세요. 각각 해당 주식의 가격을 따라갑니다. 금과 비트코인도 24시간 가능합니다.'
      ),
      points: [
        t('Empezá con poco', 'Start small', '소액으로 시작'),
        t('Cada opción te explica su riesgo antes de comprar', 'Every option explains its risk before you buy', '모든 상품은 매수 전에 위험을 설명합니다'),
      ],
      note: t(
        'No comprás la acción tradicional a tu nombre: recibís una acción digital que sigue su rendimiento. No disponible para residentes de EE.UU. ni de Brasil.',
        'You don’t buy the traditional share in your name: you receive a digital share that tracks its performance. Not available to residents of the U.S. or Brazil.',
        '전통적인 주식을 당신 명의로 사는 것이 아니라, 그 성과를 따라가는 디지털 주식을 받습니다. 미국 및 브라질 거주자에게는 제공되지 않습니다.'
      ),
      shot: nvdaShot,
      alt: t('App Confío — acción de NVIDIA', 'Confío app — NVIDIA stock', 'Confío 앱 — NVIDIA 주식'),
    },
    {
      id: 'futuros',
      kicker: t('FUTUROS', 'FUTURES', '선물'),
      title: t('Confiar en vos es decirte todo', 'Trusting you means telling you everything', '당신을 믿는다는 건 모든 걸 말해 주는 것'),
      body: t(
        'Operá futuros 24/7, en largo o en corto, desde tus dólares. En cada posición ves tu margen, el precio de liquidación y cuánto falta para llegar a él.',
        'Trade futures 24/7, long or short, from your dollars. Every position shows your margin, the liquidation price and how far away it is.',
        '내 달러로 24시간 롱 또는 숏 선물을 거래하세요. 모든 포지션에서 증거금, 청산 가격, 청산까지 남은 거리를 볼 수 있습니다.'
      ),
      points: [
        t('Tu posición vive en Hyperliquid, en una cuenta a tu nombre', 'Your position lives on Hyperliquid, in an account in your name', '포지션은 당신 명의의 Hyperliquid 계정에 있습니다'),
        t('Confío no puede moverla sin tu firma, y siempre podés cerrarla', 'Confío cannot move it without your signature, and you can always close it', 'Confío는 당신의 서명 없이 움직일 수 없고, 언제든 닫을 수 있습니다'),
      ],
      note: t(
        'Alto riesgo: con apalancamiento podés perder todo el margen de una posición. No disponible en EE.UU., Canadá, Reino Unido ni Bélgica.',
        'High risk: with leverage you can lose a position’s entire margin. Not available in the U.S., Canada, the U.K. or Belgium.',
        '고위험: 레버리지를 쓰면 포지션의 증거금 전부를 잃을 수 있습니다. 미국, 캐나다, 영국, 벨기에에서는 이용할 수 없습니다.'
      ),
      noteTone: 'risk',
      shot: futuroShot,
      alt: t('App Confío — posición de futuros abierta', 'Confío app — open futures position', 'Confío 앱 — 열린 선물 포지션'),
    },
    {
      id: 'comprar',
      kicker: t('COMPRÁ', 'SHOP', '구매하기'),
      title: t('Comprá a tiendas verificadas', 'Buy from verified shops', '검증된 가게에서 구매'),
      body: t(
        'Tu pago queda guardado mientras esperás tu pedido. Si la tienda no lo envía a tiempo, recuperás tu plata. Si no te llega, reclamá antes de que venza el plazo y revisamos el caso.',
        'Your payment is held while you wait for your order. If the shop doesn’t ship in time, you get your money back. If it doesn’t arrive, open a claim before the deadline and we review the case.',
        '주문을 기다리는 동안 결제금은 보관됩니다. 가게가 기한 안에 보내지 않으면 돈을 돌려받습니다. 도착하지 않으면 기한 전에 신고하세요. 저희가 검토합니다.'
      ),
      points: [
        t('Tiendas con identidad verificada', 'Shops with verified identity', '신원이 검증된 가게'),
        t('¿Tenés un negocio? Abrí tu tienda sin mensualidades', 'Have a business? Open your shop with no monthly fee', '사업을 하시나요? 월 이용료 없이 가게를 여세요'),
      ],
      note: t('Comprar ya está en La Paz.', 'Comprar is live in La Paz.', 'Comprar는 라파스에서 이용할 수 있습니다.'),
      shot: comprarShot,
      shotHeight: 1200,
      alt: t('App Confío — producto en una tienda verificada', 'Confío app — product from a verified shop', 'Confío 앱 — 검증된 가게의 상품'),
    },
    {
      id: 'comunidad',
      kicker: t('COMUNIDAD', 'COMMUNITY', '커뮤니티'),
      title: t('Aprendé de movimientos reales', 'Learn from real moves', '실제 거래에서 배우기'),
      body: t(
        'Mirá qué compran y venden otros miembros, con resultados reales, y sumate a la Liga del mes.',
        'See what other members buy and sell, with real results, and join the monthly League.',
        '다른 회원들이 무엇을 사고파는지 실제 결과와 함께 보고, 이달의 리그에 참여하세요.'
      ),
      points: [
        t('Compartí solo lo que vos elegís compartir', 'Share only what you choose to share', '공유하고 싶은 것만 공유하세요'),
      ],
      shot: ligaShot,
      alt: t('App Confío — Liga del mes en Comunidad', 'Confío app — monthly League in Community', 'Confío 앱 — 커뮤니티의 이달의 리그'),
    },
  ];

  return (
    <section className={styles.products} id="productos">
      <div className={styles.container}>
        <motion.div
          ref={ref}
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('UNA SOLA APP', 'ONE APP', '하나의 앱')}</span>
          <h2 className={styles.title}>
            {t('Todo lo que hacés con tus dólares,', 'Everything you do with your dollars,', '달러로 하는 모든 일,')}{' '}
            <span className={styles.highlight}>{t('a tu nombre', 'in your name', '당신 명의로')}</span>
          </h2>
        </motion.div>

        <div className={styles.rows}>
          {products.map((product, index) => (
            <ProductRow key={product.id} product={product} index={index} />
          ))}
        </div>
      </div>
    </section>
  );
};

export default FriendlyProducts;
