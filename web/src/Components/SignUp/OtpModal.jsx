import React, { useState } from "react";
import mailbox from "./../../images/Group 1.png";
import OtpInput from "react-otp-input";
import "./../../styles/SignIn.css"
import Modal from "react-modal";
const customStyles = {
  content: {
    top: "50%",
    left: "50%",
    right: "auto",
    bottom: "auto",
    transform: "translate(-50%, -50%)",
    maxWidth: "950px",
    borderRadius: "44px",
  },
};
const OtpModal = ({ toggleModal, modalIsOpen }) => {
  const [OTP, setOTP] = useState("");
  console.log("opt", OTP);
  return (
    <Modal
      isOpen={modalIsOpen}
      onRequestClose={toggleModal}
      contentLabel="Example Modal"
      style={customStyles}
      ariaHideApp={false}
    >
      <div className="popup-box">
        <div className="inner-box">
          <div>
            <img src={mailbox} alt="" className="box-img" />
          </div>
          <p className="verification">
            We have sent you a verification code on your entered email address.
            In case you can't find the code, be sure to check your spam box
          </p>
          <div id="form">
            <OtpInput
              className="otp-container"
              value={OTP}
              onChange={setOTP}
              numInputs={6}
              autoFocus
              OTPLength={6}
              otpType="number"
              disabled={false}
              secure
              separator={<span>&nbsp;&nbsp;</span>}
            />
          </div>
          <a href="/">
            <div className="verify-btn ">Verify the code</div>
          </a>
          <p className="did-not-recive">Did not receive the code?</p>
          <a href="/" className="resend">
            Resend Code
          </a>
        </div>
      </div>
    </Modal>
  );
};

export default OtpModal;
