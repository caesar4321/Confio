import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import ModernApp from './ModernApp';
import FriendlyApp from './FriendlyApp';
import './App.css';
import './ModernApp.css';
import './FriendlyApp.css';

// Choose app version based on environment variable
const appVersion = process.env.REACT_APP_VERSION || 'friendly';
let AppComponent;

switch(appVersion) {
  case 'modern':
    AppComponent = ModernApp;
    break;
  case 'classic':
    AppComponent = App;
    break;
  case 'friendly':
  default:
    AppComponent = FriendlyApp;
    break;
}

const container = document.getElementById('root');
const root = createRoot(container);
root.render(<AppComponent />);
