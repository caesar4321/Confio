import React, { useState } from 'react';
import { MenuItems2 } from './MenuItems';
import './Dropdown.css';
import { Link } from 'react-router-dom';

function Dropdown2() {

  return (
<>
      
      <ul
      >
        
        {MenuItems2.map((item, index) => {
          return (
            <li key={index}>
              <Link
                className={item.cName}
                to={item.path}
              > 
              <div className='dropdown-item'>
                <img className='dropdownIcon' src={item.src}/>
                  <div className='dropdown-item-text'>
                    {item.title}
                  </div>
              </div>

              </Link>
            </li>
          );
        })}
      </ul>
      </>
  );
}

export default Dropdown2;