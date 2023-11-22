import React from "react";
import SignUpForm from "./SignUpForm";
import WelcomeSection from "./../WelcomeSection";
import OtpModal from "./OtpModal";

const SignUp = () => {
  const [modalIsOpen, setIsOpen] = React.useState(false);

  function toggleModal() {
    setIsOpen(!modalIsOpen);
  }

  return (
    <div>
      <div className="inner-container">
        <WelcomeSection />
        <SignUpForm toggleModal={toggleModal} />
      </div>
      <div>
        <OtpModal toggleModal={toggleModal} modalIsOpen={modalIsOpen} />
      </div>
    </div>
  );
};

export default SignUp;
