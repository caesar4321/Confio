import React from "react";
import "./AboutConfio.css"
import pic from '../../images/Dashboard.png'
import AboutHeader from "../../components/FaqPage/AboutHeader";
import styles from "../../styles/TermsPage.module.css";
import "../../styles/TermsPage.module.css"

import founder_image from "../../images/founder_image.jpeg"
import linkedin from "../../images/linkedIn_icon.svg"
import discord from "../../images/discord_icon.svg"
import telegram from "../../images/telegram_icon.svg"
import tiktok from "../../images/tikTok_icon.svg"
import twitter from "../../images/twitter_icon.svg"
import instagram from "../../images/instagram_icon.svg"
import youTube from "../../images/youTube_icon.svg"


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

              <div className='about-left'>
                  <h1 className='about_heading'>About Founder</h1>
                  <p className='about-description'>
                    Founder Julian was born and raised in South Korea, where IT and banking infrastructures are phenomenally well-developed. This environment allowed Julian to experience the sleek User Experiences (UX) of Korean finance and fintech ecosystems. After Julian became fascinated by Web 3 and Blockchain, he traveled to Latin America, where he always had been interested in its culture and saw great potential in adopting blockchain in Latin America. The region’s banking infrastructures were very poor, and he had to top up various services’ balances in a rather difficult way. He was pushed to buy various gift cards from grocery stores to transfer money online. It was still heavily a cash-based society. However, at the same time, Julian witnessed Airbnb and Uber are entirely changing foreigners’ experiences in Latin America with lax regulations, or at least its local equivalents, such as Rappi and Cabify, are thriving. Julian came to see that there is room for blockchains to flourish in Latin America with lax regulations, easiness, and flexibility in adopting tech platforms with the region’s young population. Most importantly, there was a great disparity between the unbanked/underbanked population and mobile internet penetration rates. Having lived through 2 years in Latin America, Julian reconfirmed his hypothesis. Julian moved around from Paraguay to the Dominican Republic, to Costa Rica, to Panama, to Colombia, to Ecuador, to Peru, to Argentina, and to Uruguay. He wrapped up his journey at the São Paulo airport in Brazil, dreaming of entirely changing Latin America’s finances and creating the region’s biggest unicorn.
                    </p>
              </div>

              <div className='about-right'>
                <img src={founder_image} alt='logo' className='about-image'/>
              </div>

       <div className="hero-social-icons-founder">
                <div className="hs_icon">
                  <a href={ "https://www.linkedin.com/in/CryptoNomadJulian/" } target="_blank">
                  <img src={linkedin} alt="linkedin-icon"/>
                  </a>
                </div>
                <div className="hs_icon">
                  <a href={ "https://discord.com/invite/NMm7YSTzMh" } target="_blank">
                  <img src={discord} alt="discord-icon"/>
                  </a>
                </div>
                 <div className="hs_icon">
                    <a href={ "https://t.me/CryptoNomadJulian/" } target="_blank">
                    <img src={telegram} alt="telegram-icon"/>
                    </a>
                </div>
                <div className="hs_icon">
                    <a href={ "https://tiktok.com/@CryptoNomadJulian" } target="_blank">
                    <img src={tiktok} alt="tiktok-icon" />
                    </a>
                </div>
                <div className="hs_icon">
                    <a href={ "https://www.x.com/NomadJulian" } target="_blank">
                    <img src={twitter} alt="twitter-icon"/>
                    </a>
                </div>
                <div className="hs_icon">
                    <a href={ "https://www.instagram.com/CryptoNomadJulian" } target="_blank">
                    <img src={instagram} alt="instagram-icon"/>
                    </a>
                </div>
                <div className="hs_icon">
                    <a href={ "https://www.youtube.com/@CryptoNomadJulian" } target="_blank">
                    <img src={youTube} alt="youTube-icon"/>
                    </a>
                </div>
              </div>
 
     </div>
          </div>
        </div>
      </main>
    </>
  );
}
            
export default About;
