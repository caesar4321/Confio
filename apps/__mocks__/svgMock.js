// Metro turns .svg imports into components (react-native-svg-transformer);
// Jest can't parse them, so tests get a named stand-in instead.
const React = require('react');

module.exports = function SvgMock(props) {
  return React.createElement('SvgMock', props);
};
