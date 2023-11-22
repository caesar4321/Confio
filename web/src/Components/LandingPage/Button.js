import React, { useState } from 'react';
import './Button.css';
import { Link } from 'react-router-dom';

export function Button() {
  const [navbar, setNavbar] = useState(false);
  const changeNavbar = () => {
    if(window.scrollY >= 80)
    {
      setNavbar(true);
    }
    else
    {
      setNavbar(false);
    }
  };

  window.addEventListener('scroll', changeNavbar);
  return (
    <Link to='/signup'  target="_blank">
      <button className={navbar ? 'btn active' : 'btn'}>Launch App</button>
    </Link>
  );
}
