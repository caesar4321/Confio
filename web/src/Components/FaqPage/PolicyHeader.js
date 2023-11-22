import React from "react";
import styles from "../../styles/Header.module.css";

function TermsHeader() {
  return (
    <>
    {/* TERMS OF SERVICES HEADER */}
      <header className={styles.header}>
        <div className="container">
          <div className={styles.inner}>
            {/* TITLE */}
            <h1 className={`${styles.title} ${styles.less_margin}`}>
              Duende Privacy Policy
            </h1>
            {/* SUB-TITLE */}
            <h6 className={styles.sub_title}>Welcome to Duende!</h6>
          </div>
        </div>
      </header>
    </>
  );
}

export default TermsHeader;
