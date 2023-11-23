// import React from 'react';
import React, { useState } from "react";
import LanguagePack from '../../components/LanguagePack';
import ReactPlayer from "react-player";
import "../../App.css";
import { Link } from "react-router-dom";
import apple from "../../images/applepay.png";
import google from "../../images/googlepay.png";
import linkedin from "../../images/linkedIn_icon.svg"
import discord from "../../images/discord_icon.svg"
import telegram from "../../images/telegram_icon.svg"
import tiktok from "../../images/tikTok_icon.svg"
import twitter from "../../images/twitter_icon.svg"
import instagram from "../../images/instagram_icon.svg"
import youTube from "../../images/youTube_icon.svg"
import "./HeroSection.css";

function HeroSection(props) {

  const language = (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language;

  const [click1, setClick1] = useState(false);
  const [click2, setClick2] = useState(false);

  const [state, setState] = useState({
    playing: true,
    muted: true,
  });
  const { playing, muted } = state;

  const handlePlayPause = () => {
    setState({ ...state, playing: !state.playing });
  };

  const handleMuteUnMute = () => {
    setState({ ...state, muted: !state.muted });
  };

  const [copywrites, setCopyWrites] = useState([
    LanguagePack({ text: 'takeControlOfYourFinance', lang: language }),
    LanguagePack({ text: 'noMatterWhoYouAre', lang: language }),
    LanguagePack({ text: 'whatYourNationalityIs', lang: language }),
    LanguagePack({ text: 'whatYourEthnicityIs', lang: language }),
    LanguagePack({ text: 'whatYourReligionIs', lang: language }),
    LanguagePack({ text: 'whatYourGenderIs', lang: language }),
    LanguagePack({ text: 'whatYourSocialClassIs', lang: language }),
    LanguagePack({ text: 'whatYourBeliefIs', lang: language }),
    LanguagePack({ text: 'doesntMatter', lang: language }),
    LanguagePack({ text: 'allMenAreCreatedEqual', lang: language }),
    LanguagePack({ text: 'whenItComesToCryptocurrency', lang: language }),
    LanguagePack({ text: 'itDoesntDiscriminate', lang: language }),
    LanguagePack({ text: 'whentherYouAreFromVenezuela', lang: language }),
    LanguagePack({ text: 'orFromUnitedState', lang: language }),
    LanguagePack({ text: 'itDoesntDiscriminate', lang: language }),
    LanguagePack({ text: 'whetherYouAreAWallStreetBanker', lang: language }),
    LanguagePack({ text: 'orYouAreASmallChildOfIndianFarmer', lang: language }),
    LanguagePack({ text: 'itDoesntDiscriminate', lang: language }),
    LanguagePack({ text: 'whetherYouAreFightingForFreedomNow', lang: language }),
    LanguagePack({ text: 'orYouThoughtItWasADivineRight', lang: language }),
    LanguagePack({ text: 'itsABeaconOfLight', lang: language }),
    LanguagePack({ text: 'forUnderbankedPopulationAroundWorld', lang: language }),
    LanguagePack({ text: 'didYouKnow', lang: language }),
    LanguagePack({ text: 'thereAre2BillionUnbankedPeople', lang: language }),
    LanguagePack({ text: 'peopleFindItDifficultToMaintainTheirLife', lang: language }),
    LanguagePack({ text: 'theyLackOfAccessToFinancialServices', lang: language }),
    LanguagePack({ text: 'andAreMostVulnarableToFinancialCrisis', lang: language }),
    LanguagePack({ text: 'evenInMostDevelopedWorlds', lang: language }),
    LanguagePack({ text: 'thePowersTakeInnocentCitizensWealth', lang: language }),
    LanguagePack({ text: 'andImposeRestrictions', lang: language }),
    LanguagePack({ text: 'onHowYouShouldSpendYourMoney', lang: language }),
    LanguagePack({ text: 'andHowYourWealthShouldBeMeasured', lang: language }),
    LanguagePack({ text: 'itDoesntHaveToBeThatWay', lang: language }),
    LanguagePack({ text: 'withCryptocurrency', lang: language }),
    LanguagePack({ text: 'ourUnalienableRightsAreSecured', lang: language }),
    LanguagePack({ text: 'life', lang: language }),
    LanguagePack({ text: 'liberty', lang: language }),
    LanguagePack({ text: 'andThePursuitOfHappiness', lang: language }),
    LanguagePack({ text: 'itsNowTrulyForEveryone', lang: language }),
    LanguagePack({ text: 'duendeCanHelp', lang: language }),
    LanguagePack({ text: 'letsGoTogether', lang: language }),
    '',
    '',
    '',
  ]);

  return (
    <main className="mt-5 mb-5">
        <div className="container">
          <div className="hero-container">
            <h1>{copywrites[props?.currentCopyWriteIndex ?? 0]}</h1>
            <div className="bottom-section">
              <div className="hero-buttons">
                <>
                  <a href={'https://play.google.com/store/apps/details?id=com.Duende.Duende'} target="_blank">
                    <img
                      className="downloadBtn"
                      src={google}
                      alt="Get It On Google Pay"
                    />
                  </a>
                </>
                <>
                  <img className="downloadBtn" src={apple} alt="Get It On Google Pay" />
                </>

              <div className="hero-social-icons">
                <div className="hs_icon">
                <a href={ "https://www.linkedin.com/company/confio4world/" } target="_blank">
                <img src={linkedin} alt="linkedin-icon"/>
                </a>
                </div>
                <div className="hs_icon">
                <a href={ "https://discord.com/invite/NMm7YSTzMh" } target="_blank">
                <img src={discord} alt="discord-icon"/>
                </a>
                </div>
                 <div className="hs_icon">
                <a href={ "https://t.me/confio4worldgroup/" } target="_blank">
                <img src={telegram} alt="telegram-icon"/>
                </a>
                </div>
                <div className="hs_icon">
                <a href={ "https://tiktok.com/@confio4world" } target="_blank">
                <img src={tiktok} alt="tiktok-icon" />
                </a>
                </div>
                <div className="hs_icon">
                <a href={ "https://www.twitter.com/confio4world" } target="_blank">
                <img src={twitter} alt="twitter-icon"/>
                </a>
                </div>
                <div className="hs_icon">
                <a href={ "https://www.instagram.com/confio4world" } target="_blank">
                <img src={instagram} alt="instagram-icon"/>
                </a>
                </div>
                <div className="hs_icon">
                <a href={ "https://www.youtube.com/channel/UCNiWc8tG8ZRpMjXNlpBXRYg" } target="_blank">
                <img src={youTube} alt="youTube-icon"/>
                </a>
                </div>
                </div>
              </div>
              <div className="play-pause-container">
                <div className="play-pause-button" onClick={handlePlayPause}>
                  {!props?.videoPlayStatus && <i className={"fa-solid fa-play"} onClick={() => props?.playVideo()} />}
                  {props?.videoPlayStatus && <i className={"fa-solid fa-pause"} onClick={() => props?.pauseVideo()} />}
                </div>
                <div className="mute-unmute-button" onClick={handleMuteUnMute}>
                  {!props?.videoMutedStatus && <i className={"fa-solid fa-volume-up"} onClick={() => props?.switchMutedVideo()} />}
                  {props?.videoMutedStatus && <i className={"fa-solid fa-volume-mute"} onClick={() => props?.switchMutedVideo()} />}
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
  );
}

export default HeroSection;
