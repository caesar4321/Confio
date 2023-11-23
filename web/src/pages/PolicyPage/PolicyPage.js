import React, { useEffect, useState } from 'react';
import TermsHeader from "../../Components/FaqPage/PolicyHeader";
import styles from "../../styles/TermsPage.module.css";
import WebSocketInstance from '../../websocket.js';

function PolicyPage() {

  const language = (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language;

  const [isFetching, setIsFetching] = useState(false);
  const [content, setContent] = useState(null);

  useEffect(() => {
    const fetchPrivacyPolicy = async () => {
      if (isFetching)
        return;
      try {
        setIsFetching(true);
        const result = await WebSocketInstance.query(`
          query privacyPolicy ($language: String!) {
            privacyPolicy (language: $language)
          }
        `, {language: language});
        if (result?.data?.privacyPolicy)
          setContent(JSON.parse(result.data.privacyPolicy));
      } catch (error) {
        alert(error);
      } finally {
        setIsFetching(false);
      }
    };
    fetchPrivacyPolicy();
  }, []);

  return (
    <>
      <TermsHeader />
      <main>
        <div className="container">
          <div className={styles.terms_page_holder}>
            {/* TERMS LIST */}
            {content && content?.articles?.map((article, index) => <div className={styles.term_item} key={index}>
                              <h1 className={styles.heading}>{article.header}</h1>
                              {article.paragraphs.map((paragraph, index) =>
                                <p
                                  className={styles.content}
                                  key={index}
                                >
                                  {paragraph}
                                </p>)}
                            </div>)}
          </div>
        </div>
      </main>
    </>
  );
}

export default PolicyPage;
