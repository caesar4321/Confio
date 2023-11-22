import React from 'react';
import './Footer.css';
import { Link } from 'react-router-dom';

function Footer() {
  return (
    <div className='footer-container'>
      <div class='footer-links'>
        <div className='footer-link-wrapper'>
          <div class='footer-link-items'>
            <Link to='/'>About Us</Link>
            <Link to='/'>FAQ</Link>
            <Link to='/'>Whitepaper</Link>
            <Link to='/'>Token Contract Address</Link>
            <Link to='/'>Proof of Payment Stream</Link>
            <Link to='/'>Terms of Service</Link>
            <Link to='/'>Privacy Policy</Link>
          </div>
        </div>
      </div>
      <section class='social-media'>
        <div class='social-media-wrap'>
          <div class='social-icons'>
            <Link
              class='social-icon-link discord'
              to='/'
              target='_blank'
              aria-label='Discord'
            >
              <i class='fab fa-discord' />
            </Link>
            <Link
              class='social-icon-link instagram'
              to='/'
              target='_blank'
              aria-label='Instagram'
            >
              <i class='fab fa-instagram' />
            </Link>
            <Link
              class='social-icon-link youtube'
              to='/'
              target='_blank'
              aria-label='Youtube'
            >
              <i class='fab fa-youtube' />
            </Link>
            <Link
              class='social-icon-link twitter'
              to='/'
              target='_blank'
              aria-label='Twitter'
            >
              <i class='fab fa-twitter' />
            </Link>
            <Link
              class='social-icon-link twitter'
              to='/'
              target='_blank'
              aria-label='LinkedIn'
            >
              <i class='fab fa-linkedin' />
            </Link>
            <Link
              class='social-icon-link tiktok'
              to='/'
              target='_blank'
              aria-label='TikTok'
            >
              <i class='fab fa-tiktok' />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export default Footer;
