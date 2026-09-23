import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/FriendlyVision.module.css';
import { useLanguage } from '../../contexts/LanguageContext';

// «La confianza ya existe» — the same thesis as the app's Preventa and
// Moneda $CONFIO screens (apps/src/components/ConfioNarrative.tsx). Replaces
// the old quarter-by-quarter roadmap: only Dinero is a shipped product, so
// each layer carries its stage instead of a promised date.
const FriendlyVision = () => {
  const [ref, inView] = useInView({ triggerOnce: true, threshold: 0.1 });
  const { t } = useLanguage();

  const pillars = [
    {
      number: '01',
      stage: 'today',
      stageLabel: t('Hoy', 'Today', '지금'),
      title: t('Dinero', 'Money', '돈'),
      line: t('Lo tuyo, tuyo.', 'Yours is yours.', '당신의 것은 당신의 것.'),
      body: t(
        'Tus claves se crean y se usan en tu teléfono. Confío no guarda una llave maestra capaz de mover tu dinero por ti.',
        'Your keys are created and used on your phone. Confío keeps no master key that could move your money for you.',
        '키는 휴대폰에서 만들어지고 사용됩니다. Confío는 당신의 돈을 대신 움직일 수 있는 마스터 키를 보관하지 않습니다.'
      ),
    },
    {
      number: '02',
      stage: 'next',
      stageLabel: t('Lo que sigue', 'What comes next', '다음 단계'),
      title: t('Reputación', 'Reputation', '평판'),
      line: t('La confianza que construiste viaja contigo.', 'The trust you built travels with you.', '쌓아 온 신뢰가 당신과 함께 이동합니다.'),
      body: t(
        'No queremos decidir cuánto vales. Queremos ayudarte a demostrar lo que ya construiste, aunque cambies de país o de plataforma.',
        'We don’t want to decide what you’re worth. We want to help you show what you’ve already built, even when you change country or platform.',
        '당신의 가치를 우리가 정하려는 것이 아닙니다. 나라나 플랫폼이 바뀌어도 이미 쌓아 온 것을 증명할 수 있도록 돕고 싶습니다.'
      ),
    },
    {
      number: '03',
      stage: 'vision',
      stageLabel: t('Visión', 'Vision', '비전'),
      title: t('Acuerdos', 'Agreements', '약속'),
      line: t('Promesas con reglas verificables.', 'Promises with verifiable rules.', '검증 가능한 규칙을 가진 약속.'),
      body: t(
        'Que algunos compromisos puedan cumplirse con reglas públicas, sin depender por completo de una sola institución.',
        'Some commitments should be able to hold through public rules, without depending entirely on a single institution.',
        '어떤 약속은 하나의 기관에만 전적으로 의존하지 않고, 공개된 규칙으로 지켜질 수 있어야 합니다.'
      ),
    },
  ];

  return (
    <section className={styles.vision} ref={ref} id="por-que-confio">
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.badge}>{t('¿POR QUÉ SE LLAMA CONFÍO?', 'WHY IS IT CALLED CONFÍO?', '왜 이름이 Confío일까요?')}</span>
          <h2 className={styles.title}>{t('La confianza ya existe.', 'Trust already exists.', '신뢰는 이미 존재합니다.')}</h2>
          <p className={styles.subtitle}>
            {t(
              'Está en quien siempre paga. En el cliente que vuelve. En la familia que se ayuda. Pero hoy vive encerrada en un banco, en una plataforma o en un país.',
              'It’s in the person who always pays. In the customer who comes back. In the family that helps each other. But today it’s locked inside a bank, a platform or a country.',
              '늘 약속을 지키는 사람, 다시 찾아오는 손님, 서로 돕는 가족 안에 있습니다. 하지만 지금 그 신뢰는 은행, 플랫폼, 국가 안에 갇혀 있습니다.'
            )}
          </p>
          <p className={styles.emphasis}>
            {t(
              'Confío no quiere crearla desde cero. Quiere que se mueva contigo.',
              'Confío doesn’t want to create it from scratch. It wants it to move with you.',
              'Confío는 신뢰를 처음부터 만들려는 것이 아닙니다. 그 신뢰가 당신과 함께 움직이게 하려는 것입니다.'
            )}
          </p>
        </motion.div>

        <div className={styles.pillars}>
          {pillars.map((pillar, index) => (
            <motion.article
              key={pillar.number}
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.1 * (index + 1) }}
              className={`${styles.pillar} ${pillar.stage === 'today' ? styles.pillarToday : ''}`}
            >
              <div className={styles.pillarTop}>
                <span className={styles.pillarNumber}>{pillar.number}</span>
                <span className={`${styles.stage} ${pillar.stage === 'today' ? styles.stageToday : ''}`}>
                  {pillar.stageLabel}
                </span>
              </div>
              <h3 className={styles.pillarTitle}>{pillar.title}</h3>
              <p className={styles.pillarLine}>{pillar.line}</p>
              <p className={styles.pillarBody}>{pillar.body}</p>
            </motion.article>
          ))}
        </div>

        <motion.figure
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.45 }}
          className={styles.quote}
        >
          <blockquote className={styles.quoteText}>
            {t(
              '«No porque tengas que confiar ciegamente en nosotros, sino porque estamos construyendo un sistema donde puedas volver a confiar en tu propio dinero.»',
              '“Not because you have to trust us blindly, but because we’re building a system where you can trust your own money again.”',
              '“우리를 맹목적으로 믿어야 해서가 아니라, 자신의 돈을 다시 믿을 수 있는 시스템을 만들고 있기 때문입니다.”'
            )}
          </blockquote>
          <figcaption className={styles.quoteAuthor}>
            {t('Julian Moon, fundador de Confío', 'Julian Moon, founder of Confío', 'Confío 창업자 줄리안 문')}
          </figcaption>
        </motion.figure>
      </div>
    </section>
  );
};

export default FriendlyVision;
