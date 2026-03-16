import React from 'react';
import { Image, ImageStyle, StyleProp } from 'react-native';

type ResponsiveImageProps = {
  uri: string;
  style?: StyleProp<ImageStyle>;
  defaultAspectRatio?: number;
};

export function ResponsiveImage({
  uri,
  style,
  defaultAspectRatio = 4 / 3,
}: ResponsiveImageProps) {
  const [aspectRatio, setAspectRatio] = React.useState(defaultAspectRatio);

  return (
    <Image
      source={{ uri }}
      style={[style, { aspectRatio }]}
      resizeMode="contain"
      onLoad={(event) => {
        const source = event.nativeEvent.source;
        if (!source?.width || !source?.height) {
          return;
        }
        setAspectRatio(source.width / source.height);
      }}
    />
  );
}
