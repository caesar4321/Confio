import React from "react";
import "./AboutConfio.css";
import pic from "../../images/Dashboard.png";
import AboutHeader from "../../Components/FaqPage/AboutHeader";
import styles from "../../styles/TermsPage.module.css";
import "../../styles/TermsPage.module.css";

import founder_image from "../../images/founder_image.jpeg";
import linkedin from "../../images/linkedIn_icon.svg";
import tiktok from "../../images/tikTok_icon.svg";
import telegram from "../../images/telegram_icon.svg";
import twitter from "../../images/twitter_icon.svg";
import instagram from "../../images/instagram_icon.svg";
import youTube from "../../images/youTube_icon.svg";

function About() {
  return (
    <>
      <AboutHeader />
      <main>
        <div className="container">
          <div className={styles.terms_page_holder}>
            <div className="about-container">
              <div className="about-left">
                <img src={"https://sos-ch-dk-2.exo.io/duende-public/preview_image.jpeg"} alt="logo" className="about-image" />
                <h1 className="about_heading">About Confío</h1>
                <span className="about-description">
                  Confío aims to be Latin America's PayPal by helping Venezuelans and Argentines from hyperinflation by allowing them to pay and send in US dollar stablecoins.
                </span>
              </div>
            </div>
            <div className="about-container">
              <div className="about-left">
                <img src={founder_image} alt="logo" className="about-image" />
                <h1 className="about_heading">About Founder</h1>
                <span className="about-description">
                  Founder Julian was born and raised in South Korea, where IT and banking infrastructures are phenomenally well-developed. This environment
                  allowed Julian to experience the sleek User Experiences (UX) of Korean finance and fintech ecosystems. After Julian became fascinated by Web 3
                  and Blockchain, he traveled to Latin America, where he always had been interested in its culture and saw great potential in adopting
                  blockchain in Latin America. The region’s banking infrastructures were very poor, and he had to top up various services’ balances in a rather
                  difficult way. He was pushed to buy various gift cards from grocery stores to transfer money online. It was still heavily a cash-based
                  society. However, at the same time, Julian witnessed Airbnb and Uber are entirely changing foreigners’ experiences in Latin America with lax
                  regulations, or at least its local equivalents, such as Rappi and Cabify, are thriving. Julian came to see that there is room for blockchains
                  to flourish in Latin America with lax regulations, easiness, and flexibility in adopting tech platforms with the region’s young population.
                  Most importantly, there was a great disparity between the unbanked/underbanked population and mobile internet penetration rates. Having lived
                  through 2 years in Latin America, Julian reconfirmed his hypothesis. Julian nomaded from Paraguay to the Dominican Republic, Costa
                  Rica, Panama, Colombia, Ecuador, Peru, Argentina, Uruguay, Mexico, Guatemala, El Salvador, Brazil. His journey is still on-going, dreaming of entirely revolutioinalizing Latin America’s finances and creating the region’s biggest unicorn.
                </span>

                <div className="hero-social-icons-founder">
                  <div className="hs_icon">
                    <a href={"https://www.linkedin.com/in/julianmoonluna/"} target="_blank">
                      <img src={linkedin} alt="linkedin-icon" />
                    </a>
                  </div>
                  <div className="hs_icon">
                    <a href={"https://tiktok.com/@julianmoonluna"} target="_blank">
                      <img src={tiktok} alt="tiktok-icon" />
                    </a>
                  </div>
                  <div className="hs_icon">
                    <a href={"https://t.me/julianmoonluna/"} target="_blank">
                      <img src={telegram} alt="telegram-icon" />
                    </a>
                  </div>
                  <div className="hs_icon">
                    <a href={"https://x.com/julianmoonluna"} target="_blank">
                      <img src={twitter} alt="twitter-icon" />
                    </a>
                  </div>
                  <div className="hs_icon">
                    <a href={"https://instagram.com/julianmoonluna"} target="_blank">
                      <img src={instagram} alt="instagram-icon" />
                    </a>
                  </div>
                  <div className="hs_icon">
                    <a href={"https://youtube.com/@julianmoonluna"} target="_blank">
                      <img src={youTube} alt="youTube-icon" />
                    </a>
                  </div>
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
