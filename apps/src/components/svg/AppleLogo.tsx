import React from 'react';
import Svg, { Path } from 'react-native-svg';

interface AppleLogoProps {
  width?: number;
  height?: number;
}

const AppleLogo: React.FC<AppleLogoProps> = ({ width = 30, height = 30 }) => {
  return (
    <Svg width={width} height={height} viewBox="0 0 24 24">
      <Path
        d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.71-.61-3.27-.61-4.98 0-1.75.63-2.77.4-3.8-.35-5.14-4.97-4.5-10.19.5-10.36 1.76-.07 3.47.93 4.07.93.6 0 2.7-1.07 4.51-.91.76.03 2.96.31 4.36 2.34-3.91 2.37-3.28 7.17.5 8.4zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.32 2.32-1.72 4.18-3.74 4.25z"
        fill="#000000"
      />
    </Svg>
  );
};

export default AppleLogo; 