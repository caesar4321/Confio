import React from "react";
import Logo from "./../../images/logo.svg";
import "./../../styles/Signin.css"
import ELFS from "./../../images/ELFS.png";
const WelcomeSection = () => {
  return (
    <div className="left-section relative">
      <div>
        <div>
        <Link to={`/`}>
              <img src={Logo} alt="logo" className="duende-logo"/>
              </Link>
        </div>
        <h2 className="Signup-heading">Hello Again!</h2>
        <p className="signup-subHeading">Welcome back you’ve been missed</p>
        <div>
          <img src={ELFS} alt="logo" className="welcome-img2" />
        </div>
      </div>
    </div>
  );
};

export default WelcomeSection;
