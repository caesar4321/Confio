import React from "react";
import SignInForm from "./SignInForm";
import WelcomeSection from "./../WelcomeSection";

const SignIn = () => {
  return (
    <div className="inner-container">
      <WelcomeSection />
      <SignInForm />
    </div>
  );
};

export default SignIn;
