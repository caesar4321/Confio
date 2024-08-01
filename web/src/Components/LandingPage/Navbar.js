// import React from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import logo from "../../images/logo.svg";
import styles from "../../styles/Navbar.module.css";
function Navbar() {
  // OPEN SIDEBAR
  const [openNav, setOpenNav] = useState(false);

  // OPEN DuendeWorld LIST
  const [openDuendeWorldList, setOpenDuendeWorldList] = useState(false);

  // OPEN Legal LIST
  const [openLegalList, setOpenLegalList] = useState(false);

  // Change Navbar Bg Color on Scroll
  const [navBar, setNavBar] = useState(false);

  const navBarBg = () => {
    if (window.scrollY >= 10) {
      setNavBar(true);
    } else {
      setNavBar(false);
    }
  };

  const closeNavTabs = () => {
    setOpenLegalList(false);
    setOpenDuendeWorldList(false);
  };

  window.addEventListener("scroll", navBarBg);

  return (
    <>
      {/* NAVBAR */}
      <nav className={navBar ? `${styles.D_navbar} ${styles.active}` : `${styles.D_navbar}`}>
        <div className="container">
          <div className={navBar ? `${styles.inner} ${styles.active}` : `${styles.inner}`}>
            {/* LOGO */}
            <div className={navBar ? `${styles.logo} ${styles.active}` : `${styles.logo}`}>
              <Link to={`/`}>
                <img src={logo} alt="logo" className="logo_img" />
              </Link>
            </div>

            <div className={openNav ? `${styles.links} ${styles.active}` : `${styles.links}`}>
              {/* LINKS */}
              <ul className={navBar ? `${styles.navbar_list} ${styles.active}` : `${styles.navbar_list}`}>
                <Link to={`/about`}>
                  <li onMouseOver={() => closeNavTabs()} onClick={() => closeNavTabs()}>
                    About
                  </li>
                </Link>
                <Link to={`/frequently_asked_questions`}>
                  <li onMouseOver={() => closeNavTabs()} onClick={() => closeNavTabs()}>
                    FAQ
                  </li>
                </Link>
                <li
                  onMouseOver={() =>
                    setOpenDuendeWorldList((openLegalList) => {
                      setOpenLegalList(false);
                      return !openLegalList;
                    })
                  }
                  onClick={() =>
                    setOpenDuendeWorldList((openLegalList) => {
                      setOpenLegalList(false);
                      return !openLegalList;
                    })
                  }
                >
                  <span>
                    DYOR<i className="fa fa-angle-down"></i>
                    <div className={openDuendeWorldList ? `${styles.holder_hidden_list} ${styles.active}` : `${styles.holder_hidden_list}`}>
                      {/* HIDDEN LIST */}
                      <ul className={styles.hidden_list}>
                        <Link
                          to={{
                            pathname:
                              "https://medium.com/confio4world/duende-cryptocurrency-and-its-exclusive-payment-platform-to-facilitate-cryptocurrency-mass-c0a7499d0e81",
                          }}
                          target="_blank"
                        >
                          <li>Whitepaper</li>
                        </Link>
                        <Link
                          to={{
                            pathname: "https://docs.google.com/presentation/d/1wRK7VE90fOZT8rqx2My61GKYJt7SPtum9ZMO2F1CK1Q/edit?usp=sharing",
                          }}
                          target="_blank"
                        >
                          <li>Pitch Deck</li>
                        </Link>
                        <Link
                          to={{
                            pathname: "https://docs.google.com/document/d/19qr-dRVtHgyxJ97sevJZYhyeyJ4-eXjDiC4W8ZbPBt0/edit?usp=sharing",
                          }}
                          target="_blank"
                        >
                          <li>Lean Canvas</li>
                        </Link>
                        <Link to={{ pathname: "https://solscan.io/token/J4D4RmKCwmV4d93hcUrq6DQwDBWtV2eSevHGCp2PzhoH" }} target="_blank">
                          <li>Token Contract Address</li>
                        </Link>
                        <Link
                          to={{ pathname: "https://docs.google.com/spreadsheets/d/1weknEMqEiq90V53MqRGs8pZouM8ycfTwrRhWfjuAUPc/edit?usp=sharing" }}
                          target="_blank"
                        >
                          <li>Token Distribution</li>
                        </Link>
                      </ul>
                    </div>
                  </span>
                </li>
                <li
                  onMouseOver={() =>
                    setOpenLegalList((openLegalList) => {
                      setOpenDuendeWorldList(false);
                      return !openLegalList;
                    })
                  }
                  onClick={() =>
                    setOpenLegalList((openLegalList) => {
                      setOpenDuendeWorldList(false);
                      return !openLegalList;
                    })
                  }
                >
                  <span>
                    Legal<i className="fa fa-angle-down"></i>
                    <div className={openLegalList ? `${styles.holder_hidden_list} ${styles.active}` : `${styles.holder_hidden_list}`}>
                      {/* HIDDEN LIST */}
                      <ul className={styles.hidden_list}>
                        <Link to={`/terms_of_service`}>
                          <li>Terms of Service</li>
                        </Link>
                        <Link to={`/privacy_policy`}>
                          <li>Privacy Policy</li>
                        </Link>
                      </ul>
                    </div>
                  </span>
                </li>
              </ul>
            </div>

            {/* BUTTON 
            <button className={navBar ? `button ${styles.active}` : `button`}>
              <Link to="signin" target="_blank">Launch App</Link>
            </button>*/}

            {/* HAMBURGER */}
            <div class={styles.hamburger} onClick={() => setOpenNav(!openNav)}>
              <input class={styles.checkbox} type="checkbox" />
              <div
                class={
                  openNav
                    ? `${styles.hamburger_lines} ${styles.active}`
                    : `${styles.hamburger_lines}` && navBar
                      ? `${styles.hamburger_lines} ${styles.color_active}`
                      : `${styles.hamburger_lines}`
                }
              >
                <span class={`${styles.line} ${styles.line1}`}></span>
                <span class={`${styles.line} ${styles.line2}`}></span>
                <span class={`${styles.line} ${styles.line3}`}></span>
              </div>
            </div>
          </div>
        </div>
      </nav>
    </>
  );
}

export default Navbar;
