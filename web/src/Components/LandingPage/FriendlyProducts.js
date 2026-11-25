import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyProducts.module.css';
import { useLanguage } from '../../contexts/LanguageContext';
import remesasShot from '../../images/screens/remesas.jpg';
import accionesShot from '../../images/screens/acciones.jpg';
import comprasShot from '../../images/screens/compras.jpg';
import whatsappShot from '../../images/screens/whatsapp.jpg';
import qrShot from '../../images/screens/qr.jpg';
import firmaShot from '../../images/screens/firma.jpg';

// One row per thing you can ask for, in the store listing's order, each with
// its chat (DESIGN.md: the product is the proof). The screens are drawn from
// the app's own styles and the server's real wording; names and amounts in
// them are example data, never a member's.
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
        {product.ask && <p className={styles.ask}>{product.ask}</p>}
        <p className={styles.rowBody}>{product.body}</p>
        <ul className={styles.points}>
          {product.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        {product.note && <p className={styles.note}>{product.note}</p>}
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
            height={1300}
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
  const [moreRef, moreInView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const { t } = useLanguage();

  const products = [
    {
      id: 'enviar',
      kicker: t('REMESAS Y ENVÍOS', 'REMITTANCES AND TRANSFERS', '송금'),
      title: t('Mandá plata a tu familia', 'Send money to your family', '가족에게 돈을 보내세요'),
      ask: t('«Mandale plata a mi mamá.»', '“Send money to my mom.”', '“엄마에게 돈 보내 줘.”'),
      body: t(
        'Enviá dólares a otra persona en segundos, aunque viva en otro país. Confío te pregunta el monto, te muestra a quién le llega y cuánto, y vos lo confirmás.',
        'Send dollars to another person in seconds, even in another country. Confío asks the amount, shows you who receives it and how much, and you confirm.',
        '다른 나라에 사는 사람에게도 몇 초 만에 달러를 보내세요. Confío가 금액을 묻고, 누가 얼마를 받는지 보여 주면 당신이 확인합니다.'
      ),
      points: [
        t('A cuentas bancarias en la región, con el monto exacto que llega antes de confirmar', 'To bank accounts in the region, with the exact amount that arrives shown before you confirm', '역내 은행 계좌로도 송금: 확인 전에 도착 금액을 정확히 표시'),
        t('Recargá desde tu banco o billetera: Pix, Bre-B, CLABE, Pago Móvil y más países', 'Top up from your bank or wallet: Pix, Bre-B, CLABE, Pago Móvil and more countries', '은행이나 지갑에서 충전: Pix, Bre-B, CLABE, Pago Móvil 등 여러 나라'),
        t('Recibí USDT desde otra billetera', 'Receive USDT from another wallet', '다른 지갑에서 USDT 받기'),
      ],
      shot: remesasShot,
      alt: t('App Confío — un envío preparado en el chat', 'Confío app — a transfer prepared in the chat', 'Confío 앱 — 대화에서 준비된 송금'),
    },
    {
      id: 'invertir',
      kicker: t('INVERTÍ', 'INVEST', '투자하기'),
      title: t('Acciones de EE.UU., con solo pedirlo', 'U.S. stocks, just by asking', '말 한마디로 미국 주식'),
      ask: t('«Comprá NVIDIA.»', '“Buy NVIDIA.”', '“NVIDIA 사 줘.”'),
      body: t(
        'Pedilo y Confío te pregunta cuántos dólares. Son acciones digitales de Tesla, NVIDIA y más, emitidas por Ondo Stocks. Cada una sigue el precio de su acción.',
        'Ask, and Confío asks you how many dollars. They are digital shares of Tesla, NVIDIA and more, issued by Ondo Stocks. Each one tracks its stock’s price.',
        '요청하면 Confío가 몇 달러인지 묻습니다. Ondo Stocks가 발행한 Tesla, NVIDIA 등의 디지털 주식이며, 각각 해당 주식의 가격을 따라갑니다.'
      ),
      points: [
        t('Empezá con poco', 'Start small', '소액으로 시작'),
        t('Ves el precio, la comisión y cuánto recibís antes de aprobar', 'You see the price, the fee and how much you receive before you approve', '승인 전에 가격, 수수료, 받을 수량을 확인'),
      ],
      note: t(
        'Su precio sube y baja: podés perder dinero. No comprás la acción tradicional a tu nombre: recibís una acción digital que sigue su rendimiento. No disponible en EE.UU., Canadá, Brasil, la Unión Europea, el Reino Unido y algunos otros países.',
        'The price goes up and down: you can lose money. You don’t buy the traditional share in your name: you receive a digital share that tracks its performance. Not available in the U.S., Canada, Brazil, the European Union, the U.K. and some other countries.',
        '가격은 오르내리며 돈을 잃을 수 있습니다. 전통적인 주식을 당신 명의로 사는 것이 아니라, 그 성과를 따라가는 디지털 주식을 받습니다. 미국, 캐나다, 브라질, 유럽연합, 영국 및 일부 다른 국가에서는 제공되지 않습니다.'
      ),
      shot: accionesShot,
      alt: t('App Confío — compra de NVIDIA lista para aprobar en el chat', 'Confío app — a NVIDIA purchase ready to approve in the chat', 'Confío 앱 — 대화에서 승인 대기 중인 NVIDIA 매수'),
    },
    {
      id: 'compras',
      kicker: t('COMPRAS EN LÍNEA', 'ONLINE SHOPPING', '온라인 쇼핑'),
      title: t('Compras en línea: Confío las hace por vos', 'Online shopping, done for you', '온라인 쇼핑을 대신해 드립니다'),
      ask: t(
        '«Comprame unos audífonos de menos de 600 pesos, que lleguen a mi casa.»',
        '“Buy me headphones under 600 pesos, delivered to my home.”',
        '“600페소 이하 헤드폰을 사서 집으로 보내 줘.”'
      ),
      body: t(
        'Decile qué querés comprar. Confío busca el producto, arma el pedido y te lo muestra antes de pagar.',
        'Say what you want to buy. Confío finds the product, puts the order together and shows it to you before paying.',
        '사고 싶은 것을 말하세요. Confío가 상품을 찾고 주문을 구성한 뒤, 결제 전에 보여 줍니다.'
      ),
      points: [
        t('Vos confirmás el pedido y el pago', 'You confirm the order and the payment', '주문과 결제는 당신이 확인'),
        t('Pagás desde tus dólares', 'You pay from your dollars', '내 달러로 결제'),
      ],
      note: t(
        'Las compras en tiendas en línea se pagan con Pix en Brasil y SPEI en México.',
        'Online store purchases are paid with Pix in Brazil and SPEI in Mexico.',
        '온라인 쇼핑 결제는 브라질의 Pix와 멕시코의 SPEI로 이루어집니다.'
      ),
      shot: comprasShot,
      alt: t('App Confío — un pedido en una tienda en línea, listo para confirmar', 'Confío app — an online store order, ready to confirm', 'Confío 앱 — 확인 대기 중인 온라인 쇼핑 주문'),
    },
    {
      id: 'mensajes',
      kicker: t('WHATSAPP, CORREO Y AGENDA', 'WHATSAPP, EMAIL AND CALENDAR', 'WHATSAPP, 메일, 일정'),
      title: t('Tu WhatsApp, tu correo y tu agenda, al día', 'Your WhatsApp, email and calendar, up to date', 'WhatsApp, 메일, 일정을 한눈에'),
      ask: t('«¿Algo importante en mi WhatsApp?»', '“Anything important on my WhatsApp?”', '“내 WhatsApp에 중요한 거 있어?”'),
      body: t(
        'Vinculá tu WhatsApp con un código: Confío revisa tus mensajes, te avisa de lo importante y escribe por vos. Antes de enviar algo, te lo muestra.',
        'Link your WhatsApp with a code: Confío checks your messages, tells you what matters and writes for you. Before sending anything, it shows it to you.',
        '코드로 WhatsApp을 연결하면 Confío가 메시지를 확인해 중요한 것을 알려 주고 대신 작성합니다. 보내기 전에는 항상 먼저 보여 줍니다.'
      ),
      points: [
        t('Lo mismo con tu Gmail y tu calendario: te resume tus correos y te recuerda lo que viene', 'The same with your Gmail and calendar: it sums up your email and reminds you of what’s coming', 'Gmail과 캘린더도 마찬가지: 메일을 요약하고 다가오는 일정을 알려 줍니다'),
        t('Vos decidís qué conectás y podés desconectarlo cuando quieras', 'You decide what to connect and can disconnect it whenever you want', '무엇을 연결할지는 당신이 정하고, 언제든 연결을 끊을 수 있습니다'),
      ],
      shot: whatsappShot,
      alt: t('App Confío — resumen de WhatsApp y una respuesta lista para enviar', 'Confío app — a WhatsApp summary and a reply ready to send', 'Confío 앱 — WhatsApp 요약과 전송 대기 중인 답장'),
    },
    {
      id: 'pagar',
      kicker: t('PAGÁ', 'PAY', '결제하기'),
      title: t('Pagá cualquier QR', 'Pay any QR', '어떤 QR이든 결제'),
      ask: t('«Pagá este QR.»', '“Pay this QR.”', '“이 QR 결제해 줘.”'),
      body: t(
        'Pegá el código o escanealo. Confío prepara el pago, te muestra el comercio, el monto y el total, y vos lo confirmás.',
        'Paste the code or scan it. Confío prepares the payment, shows you the merchant, the amount and the total, and you confirm.',
        '코드를 붙여 넣거나 스캔하세요. Confío가 결제를 준비하고 가맹점, 금액, 합계를 보여 주면 당신이 확인합니다.'
      ),
      points: [
        t('Pagá y cobrá también con el QR de Confío', 'Pay and get paid with the Confío QR too', 'Confío QR로도 결제하고 받을 수 있습니다'),
      ],
      note: t(
        'Los QR locales que podés pagar dependen de tu país.',
        'The local QR codes you can pay depend on your country.',
        '결제할 수 있는 현지 QR은 나라에 따라 다릅니다.'
      ),
      shot: qrShot,
      alt: t('App Confío — pago de un QR preparado en el chat', 'Confío app — a QR payment prepared in the chat', 'Confío 앱 — 대화에서 준비된 QR 결제'),
    },
    {
      id: 'firma',
      kicker: t('VOS DECIDÍS', 'YOU DECIDE', '결정은 당신이'),
      title: t('Nada se mueve sin tu firma', 'Nothing moves without your signature', '당신의 서명 없이는 아무것도 움직이지 않습니다'),
      body: t(
        'Antes de cada pago o inversión ves el monto, la comisión y el total. Lo aprobás con tu cara o tu huella, y recién ahí se mueve.',
        'Before every payment or investment you see the amount, the fee and the total. You approve it with your face or fingerprint, and only then does it move.',
        '모든 결제나 투자 전에 금액, 수수료, 합계를 확인합니다. 얼굴이나 지문으로 승인해야만 비로소 움직입니다.'
      ),
      points: [
        t('El monto lo escribís vos', 'You type the amount yourself', '금액은 당신이 직접 입력'),
        t('Si decís «no», Confío cancela en ese momento lo que preparó', 'If you say “no”, Confío cancels what it prepared right then', '“아니요”라고 하면 Confío가 준비한 것을 그 자리에서 취소합니다'),
        t('Tus dólares están en una billetera a tu nombre', 'Your dollars sit in a wallet in your name', '달러는 당신 명의의 지갑에 있습니다'),
      ],
      shot: firmaShot,
      alt: t('App Confío — «Revisa antes de pagar», con el monto, la comisión y el total', 'Confío app — “Review before paying”, with the amount, the fee and the total', 'Confío 앱 — 금액, 수수료, 합계가 표시된 결제 전 확인 화면'),
    },
  ];

  const more = [
    {
      title: t('Lo del día a día', 'Everyday things', '일상의 일들'),
      body: t(
        'Traducí un mensaje, redactá un correo, planeá un viaje o buscá información actual en internet, en el mismo chat.',
        'Translate a message, draft an email, plan a trip or look up current information online, in the same chat.',
        '메시지 번역, 메일 작성, 여행 계획, 최신 정보 검색까지 같은 대화에서.'
      ),
    },
    {
      title: t('Comunidad', 'Community', '커뮤니티'),
      body: t(
        'Mirá qué compran y venden otros miembros, con resultados reales, y sumate a la Liga del mes.',
        'See what other members buy and sell, with real results, and join the monthly League.',
        '다른 회원들이 무엇을 사고파는지 실제 결과와 함께 보고, 이달의 리그에 참여하세요.'
      ),
    },
    {
      title: t('Comprar', 'Comprar', 'Comprar'),
      body: t(
        'Comprá a tiendas verificadas: tu pago queda guardado mientras esperás tu pedido. Ya está en La Paz.',
        'Buy from verified shops: your payment is held while you wait for your order. Live in La Paz.',
        '검증된 가게에서 구매하세요. 주문을 기다리는 동안 결제금은 보관됩니다. 라파스에서 이용할 수 있습니다.'
      ),
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
          <span className={styles.badge}>{t('UN SOLO CHAT', 'ONE CHAT', '하나의 대화')}</span>
          <h2 className={styles.title}>
            {t('Lo que necesitás,', 'What you need,', '필요한 일,')}{' '}
            <span className={styles.highlight}>{t('con solo pedirlo', 'just by asking', '말 한마디로')}</span>
          </h2>
        </motion.div>

        <div className={styles.rows}>
          {products.map((product, index) => (
            <ProductRow key={product.id} product={product} index={index} />
          ))}
        </div>

        <motion.div
          ref={moreRef}
          initial={{ opacity: 0, y: 24 }}
          animate={moreInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5 }}
          className={styles.more}
        >
          <h3 className={styles.moreTitle}>{t('Y también', 'And also', '그리고')}</h3>
          <div className={styles.moreGrid}>
            {more.map((item) => (
              <div key={item.title} className={styles.moreCard}>
                <h4 className={styles.moreCardTitle}>{item.title}</h4>
                <p className={styles.moreCardBody}>{item.body}</p>
              </div>
            ))}
          </div>
          <p className={styles.availability}>
            {t(
              'La disponibilidad de cada producto depende de tu país.',
              'The availability of each product depends on your country.',
              '각 상품의 이용 가능 여부는 나라에 따라 다릅니다.'
            )}
          </p>
        </motion.div>
      </div>
    </section>
  );
};

export default FriendlyProducts;
