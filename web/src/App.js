import React from 'react';
import "react-accessible-accordion/dist/fancy-example.css";
import Navbar from './components/LandingPage/Navbar';
import './App.css';
import Home from './pages/Home';
import { BrowserRouter as Router, Switch, Route } from 'react-router-dom';
import FaqPage from './pages/FaqPage/FaqPage'
import TermsPage from './pages/TermsPage/TermsPage'
import SignIn from './components/SignIn/index'
import SignUp from './components/SignUp/index'
import PolicyPage from './pages/PolicyPage/PolicyPage'
import About from './components/LandingPage/AboutConfio'


function App() {
  return (
    <Router>
      
        <Route path="/signin" element component={SignIn} />
        <Route path="/signup" element component={SignUp} />
        <Navbar />
        <Switch>
        <Route path='/' exact component={Home} />
          <Route path='/about' exact component={About} />
          <Route path='/faq' exact component={FaqPage} />
          <Route path='/terms_of_services' exact component={TermsPage} />
          <Route path='/privacy_policy' exact component={PolicyPage} />
        </Switch>
    </Router>
  )
}

export default App;
