// Development environment uses Sui's test client ID
// Production environment uses our own client ID
export const GOOGLE_CLIENT_IDS = {
  development: {
    web: '1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com',
    ios: '1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com',
    android: '1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com'
  },
  production: {
    web: '730050241347-99hd2fsigoearsbgo2j1esng2rn7qg99.apps.googleusercontent.com',
    ios: '730050241347-m60gqh7aahb818c6g7vb4jkpkl5iauld.apps.googleusercontent.com',
    android: '730050241347-ft2v34hm2okng97rb4on37kr9qt9lbhp.apps.googleusercontent.com'
  }
} as const;

export const getGoogleClientIds = () => {
  // For testing, we can force production environment
  return GOOGLE_CLIENT_IDS['production'];
  // return GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
}; 