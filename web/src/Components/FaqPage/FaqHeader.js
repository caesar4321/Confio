import React from "react";
import '../../App.css'
import styles from "../../styles/Header.module.css";

function FaqHeader() {
  return (
    <>
    {/* FAQ HEADER */}
      <header className={styles.header}>
        <div className="container">
          <div className={styles.inner}>
          {/* TITLE */}
            <h1 className={styles.title}>Frequently Asked Questions</h1>
            <div className="col-lg-7" style={{margin:"0 auto"}}>

            {/* SEARCH BAR 
            <div className={styles.search_bar}>
            <input placeholder="Search" type="search"/>
              <i class="fa fa-search"></i>
            </div>*/}
            </div>
          </div>
        </div>
      </header>
    </>
  );
}

export default FaqHeader;
