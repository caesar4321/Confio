import React from "react";
import "./AboutDuende.css"
import pic from '../../images/Dashboard.png'
import AboutHeader from "../../components/FaqPage/AboutHeader";
import styles from "../../styles/TermsPage.module.css";
import "../../styles/TermsPage.module.css"


function About() {
  return (
    <>
      <AboutHeader />
      <main>
        <div className="container">
          <div className={styles.terms_page_holder}>
           <div className='about-container'>
      <div className='about-left'>
          <h1 className='about_heading'>About Confío</h1>
          <p className='about-description'>
            Confío aims to be Latin America's PayPal by helping Venezuelans and Argentines from hyperinflation by allowing them to pay in US dollar stablecoins.
            </p>
      </div>
      <div className='about-right'>
        <img src={'https://duende-public.duende.me/preview_image.jpeg'} alt='logo' className='about-image'/>
      </div>
 
     </div>
          </div>
        </div>
      </main>
    </>
  );
}
            
export default About;
