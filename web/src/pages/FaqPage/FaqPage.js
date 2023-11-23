import React, { useEffect, useState } from 'react';
import FaqHeader from "../../Components/FaqPage/FaqHeader";
import WebSocketInstance from '../../websocket.js';
import '../../styles/FaqAccordion.css'
import styles from '../../styles/FaqPage.module.css'
import {
  Accordion,
  AccordionItem,
  AccordionItemHeading,
  AccordionItemButton,
  AccordionItemPanel,
} from "react-accessible-accordion";
import Linkify from 'react-linkify';

function FaqPage() {
  const language = (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language;
  
  const [isFetching, setIsFetching] = useState(false);
  const [content, setContent] = useState(null);

  useEffect(() => {
    const fetchFrequentlyAskedQuestions = async () => {
      if (isFetching)
        return;
      try {
        setIsFetching(true);
        const result = await WebSocketInstance.query(`
          query frequentlyAskedQuestions ($language: String!) {
            frequentlyAskedQuestions (language: $language)
          }
        `, {language: language});
        if (result?.data?.frequentlyAskedQuestions)
          setContent(JSON.parse(result.data.frequentlyAskedQuestions));
      } catch (error) {
        alert(error);
      } finally {
        setIsFetching(false);
      }
    };
    fetchFrequentlyAskedQuestions();
  }, []);

  return (
    <>
      <FaqHeader/>
      <main className="mt-5 mb-5">
        <div className="container">
          <div className="row">
            {/*
            <div className="col-lg-4">
              <div className={styles.faq_side_menu}>
                <div className={styles.categories_sec}>
                  <h2 className={styles.title}>Categories</h2>
                  <ul className={styles.categories_list}>
                    <li>General</li>
                    <li>Legal</li>
                    <li>Economy</li>
                    <li>Transactions</li>
                    <li>Mining</li>
                    <li>Security</li>
                    <li>Help</li>
                  </ul>
                </div>

                <div className={styles.tags_sec}>
                  <h2 className={styles.title}>Tags</h2>
                  <ul className={styles.tags_list}>
                    <li>Duende</li>
                    <li>Transfer</li>
                    <li>Map</li>
                    <li>Duende</li>
                    <li>Duende</li>
                  </ul>
                </div>
              </div>
            </div>
            */}
            {/* ACCORDIONS */}
              <Accordion allowZeroExpanded>
                {content && content?.articles?.map((article, index) => <Linkify
                  componentDecorator={(decoratedHref, decoratedText, key) => (
                      <a target="_blank" href={decoratedHref} key={key}>
                          {decoratedText}
                      </a>
                  )}>
                    <AccordionItem key={index}>
                    <AccordionItemHeading>
                      <AccordionItemButton>{article.header}</AccordionItemButton>
                    </AccordionItemHeading>
                    <AccordionItemPanel>{article.paragraphs.map((paragraph, index) =>
                                <p
                                  key={index}
                                >
                                  {paragraph}
                                </p>)}</AccordionItemPanel>
                  </AccordionItem>
                    </Linkify>)}
              </Accordion>
          </div>
        </div>
      </main>
    </>
  );
}

export default FaqPage;
