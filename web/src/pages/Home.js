import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import '../App.css';
import HeroSection from '../Components/LandingPage/HeroSection';
import Footer from '../Components/LandingPage/Footer';
import About from '../Components/LandingPage/AboutConfio'

window.history.pushState(null, null, window.location.href);
window.onpopstate = function(event) {
  window.history.go(1);
};

function Home() {
  const videoRef = useRef(null);
  const [videoPlayStatus, setVideoPlayStatus] = useState(true);
  const [videoMutedStatus, setVideoMutedStatus] = useState(true);
  const location = useLocation();
  const [currentCopyWriteIndex, setCurrentCopyWriteIndex] = useState(0);

  useEffect(() => {
    const regex = new RegExp('^[a-z]{2}/$');
    if (location.pathname == '/' || regex.test(location.pathname))
      playVideo();
    else
      pauseVideo();
  }, [location.pathname])

  const playVideo = () => {
    videoRef.current.play();
  };

  const pauseVideo = () => {
    videoRef.current.pause();
  };

  const switchMutedVideo = () => {
    if (videoMutedStatus) {
      videoRef.current.muted = false;
      setVideoMutedStatus(false);
    } else {
      videoRef.current.muted = true;
      setVideoMutedStatus(true);
    }
  };

  return (
    <div
      className="App"
      style={{
        position: 'absolute',
        width: '100%',
        height: '100%',
        display: 'flex',
        padding: '5vw',
      }}>
      <video
        ref={videoRef}
        autoPlay
        loop
        muted={true}
        onPlay={() => setVideoPlayStatus(true)}
        onPause={() => setVideoPlayStatus(false)}
        onTimeUpdate={e => setCurrentCopyWriteIndex(Math.floor(e.target.currentTime/3) % 44)}
        style={{
          position: 'absolute',
          width: '100%',
          left: '50%',
          top: '50%',
          height: '100%',
          objectFit: 'cover',
          transform: 'translate(-50%,-50%)',
          zIndex: -1,
//          opacity: 0.5,
        }}
      >
        <source src='https://duende-public.sos-ch-dk-2.exoscale-cdn.com/introduction.mp4' type='video/mp4' />
      </video>
      <HeroSection currentCopyWriteIndex={currentCopyWriteIndex} videoPlayStatus={videoPlayStatus} videoMutedStatus={videoMutedStatus} playVideo={playVideo} pauseVideo={pauseVideo} switchMutedVideo={switchMutedVideo} />
      {/* <About/>
      <Footer /> */}
    </div>
  );
}

export default Home;
