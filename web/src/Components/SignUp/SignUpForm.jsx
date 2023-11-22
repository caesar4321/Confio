import React from "react";
import "./../../styles/SignIn.css"
import { Link } from "react-router-dom";
const SignUpForm = ({ toggleModal }) => {

  return (
    <div className="signup right-section">
      <div className="right-inner-section">
        <h1 className="signup-title">Sign Up</h1>
        <form autoComplete="off" className="w-100">
          <div>
            <input
              type="text"
              placeholder="Enter  Username"
              className="signUp-input"
              name="username"
            />
          </div>
          <div>
            <input
              type="email"
              placeholder="manpreetkaur0699@gmail.com"
              className="signUp-input"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder="Enter Password"
              className="signUp-input"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder="Re-Enter Password"
              className="signUp-input"
            />
          </div>
        </form>
        <button
          type="submit"
          value="Sign Up"
          onClick={toggleModal}
          className="signUp-btn"
        >
          Sign Up
        </button>
        <p className="forgot-pass">Forgot Password</p>
        <p className="if-already-sigup">
          Having an account?{" "}
          <Link to="/signin" className="sign-btn">
            Sign In
          </Link>
        </p>
      </div>
    </div>
  );
};

export default SignUpForm;
