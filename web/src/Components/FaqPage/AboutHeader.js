import React from "react";
import styles from "../../styles/About.module.css";

function AboutHeader() {
  return (
    <>
    {/* TERMS OF SERVICES HEADER */}
      <header className={styles.header}>
        <div className="container">
          <div className={styles.inner}>
          {/* <h1 className={`${styles.title} ${styles.less_margin}`}>
              Lets know about Duende
            </h1> */}
          </div>
        </div>
      </header>
    </>
  );
}

export default AboutHeader;
