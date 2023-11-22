import React from "react";
import { Link } from "react-router-dom";
import "./../../styles/SignIn.css"

const SignInForm = () => {
  return (
    <div className="sign-in right-section">
      <div className="right-inner-section">
        <h1 className="signup-title">Log In</h1>
        <form autoComplete="off" className="w-100">
          <input
            type="text"
            placeholder="Enter  Username"
            className="signUp-input "
          />
          <br />
          <input
            type="password"
            placeholder="Enter Password"
            className="signUp-input"
          />
          <br />
          <button type="button" value="Sign In" className="signUp-btn">
            Sign In
          </button>
          <a href="/" className="forgot-pass">
            Forgot Password
          </a>
        </form>
        <p className="if-already-sigup">
          Dont have an account?
          <Link to="/signup" className="sign-btn">
            Sign Up
          </Link>
        </p>
      </div>
    </div>
  );
};

export default SignInForm;
