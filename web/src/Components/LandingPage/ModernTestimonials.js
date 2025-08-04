import React from 'react';
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import styles from '../../styles/ModernTestimonials.module.css';

const ModernTestimonials = () => {
  const [ref, inView] = useInView({
    triggerOnce: true,
    threshold: 0.1
  });

  const testimonials = [
    {
      name: 'María González',
      role: 'Emprendedora',
      country: '🇻🇪 Venezuela',
      content: 'Confío me permite recibir pagos de mis clientes internacionales sin las complicaciones bancarias tradicionales.',
      rating: 5,
      avatar: '👩‍💼'
    },
    {
      name: 'Carlos Rodríguez',
      role: 'Freelancer',
      country: '🇦🇷 Argentina',
      content: 'Por fin puedo ahorrar en dólares digitales y proteger mi dinero de la inflación. La app es super fácil de usar.',
      rating: 5,
      avatar: '👨‍💻'
    },
    {
      name: 'Ana Martínez',
      role: 'Comerciante',
      country: '🇲🇽 México',
      content: 'El P2P exchange es increíble. Puedo cambiar mis pesos por dólares digitales cuando quiera, con tarifas justas.',
      rating: 5,
      avatar: '👩‍🏫'
    }
  ];

  return (
    <section className={styles.testimonials} ref={ref}>
      <div className={styles.container}>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6 }}
          className={styles.header}
        >
          <span className={styles.label}>TESTIMONIOS</span>
          <h2 className={styles.title}>
            Lo que dicen nuestros
            <span className={styles.gradientText}> usuarios</span>
          </h2>
          <p className={styles.subtitle}>
            Miles de latinoamericanos ya confían en nosotros
          </p>
        </motion.div>

        <div className={styles.grid}>
          {testimonials.map((testimonial, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: index * 0.1 }}
              className={styles.card}
              whileHover={{ y: -5 }}
            >
              <div className={styles.rating}>
                {[...Array(testimonial.rating)].map((_, i) => (
                  <span key={i} className={styles.star}>⭐</span>
                ))}
              </div>
              
              <p className={styles.content}>"{testimonial.content}"</p>
              
              <div className={styles.author}>
                <div className={styles.avatar}>
                  <span>{testimonial.avatar}</span>
                </div>
                <div className={styles.authorInfo}>
                  <h4 className={styles.name}>{testimonial.name}</h4>
                  <p className={styles.role}>{testimonial.role}</p>
                  <p className={styles.country}>{testimonial.country}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.4 }}
          className={styles.stats}
        >
          <div className={styles.statCard}>
            <h3 className={styles.statNumber}>10,000+</h3>
            <p className={styles.statLabel}>Usuarios Activos</p>
          </div>
          <div className={styles.statCard}>
            <h3 className={styles.statNumber}>$5M+</h3>
            <p className={styles.statLabel}>Transaccionado</p>
          </div>
          <div className={styles.statCard}>
            <h3 className={styles.statNumber}>15+</h3>
            <p className={styles.statLabel}>Países</p>
          </div>
          <div className={styles.statCard}>
            <h3 className={styles.statNumber}>4.9/5</h3>
            <p className={styles.statLabel}>Calificación</p>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default ModernTestimonials;