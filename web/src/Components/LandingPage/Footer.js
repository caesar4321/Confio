import React from 'react';
import { Link } from 'react-router-dom';
import './Footer.css';

const Footer = () => {
  return (
    <footer className="footer">
      <div className="footer-content">
        <div className="footer-links">
          <Link to="/terms" className="footer-link">Términos de Servicio</Link>
          <Link to="/privacy" className="footer-link">Política de Privacidad</Link>
          <Link to="/deletion" className="footer-link">Eliminación de Datos</Link>
        </div>
        <div className="footer-copyright">
          © {new Date().getFullYear()} Confío. Todos los derechos reservados.
        </div>
      </div>
    </footer>
  );
};

export default Footer; 