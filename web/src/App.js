import React from 'react';
import "react-accessible-accordion/dist/fancy-example.css";
import Navbar from './Components/LandingPage/Navbar';
import './App.css';
import Home from './pages/Home';
import { BrowserRouter as Router, Switch, Route } from 'react-router-dom';
import FaqPage from './pages/FaqPage/FaqPage'
import TermsPage from './pages/TermsPage/TermsPage'
import SignIn from './Components/SignIn/index'
import SignUp from './Components/SignUp/index'
import PolicyPage from './pages/PolicyPage/PolicyPage'
import About from './Components/LandingPage/AboutConfio'


function App() {
  return (
    <Router>
      
        <Route path="/signin" element component={SignIn} />
        <Route path="/signup" element component={SignUp} />
        <Navbar />
        <Switch>
        <Route path='/' exact component={Home} />
          <Route path='/about' exact component={About} />
          <Route path='/frequently_asked_questions' exact component={FaqPage} />
          <Route path='/terms_of_service' exact component={TermsPage} />
          <Route path='/privacy_policy' exact component={PolicyPage} />
        </Switch>
    </Router>
  )
}

export default App;
