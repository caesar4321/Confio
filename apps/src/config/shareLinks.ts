// Centralized share links configuration
export const SHARE_LINKS = {
  // Campaign links for different share contexts
  campaigns: {
    beta: 'https://confio.lat/wa',
    referral: 'https://confio.lat/wa-ref', 
    tiktok: 'https://confio.lat/wa-tiktok',
    tiktokCreator: 'https://confio.lat/tiktok',
    telegram: 'https://confio.lat/telegram',
  },
  
  // App store links (update these when live)
  stores: {
    android: 'https://play.google.com/store/apps/details?id=com.Confio.Confio',
    ios: 'https://apps.apple.com/app/id6472662314',
    testflight: 'https://testflight.apple.com/join/YOUR_CODE', // Update with actual code
  },
  
  // Landing pages
  web: {
    landing: 'https://confio.lat',
    userAddress: (username: string) => `https://confio.lat/@${username}`,
  },
  
  // Share messages templates
  messages: {
    beta: '¡Únete a Confío! 💚\nLa billetera digital diseñada para Venezuela.\n\n',
    referral: '¡Te invito a Confío! 💸\nGana $2 por cada amigo que invites.\n\n',
    achievement: '¡Mira lo que logré en Confío! 🏆\n\n',
    tiktok: '¡Sígueme en mi reto Confío! 🎬\n\n',
    transaction: '¡Te envié dinero por Confío! 💰\n\n',
  },
  
  // Official hashtags (never change these)
  hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
};

// Helper function to get the appropriate share link based on context
export const getShareLink = (context: 'beta' | 'referral' | 'tiktok' | 'tiktokCreator' | 'telegram' | 'general' = 'beta') => {
  switch (context) {
    case 'referral':
      return SHARE_LINKS.campaigns.referral;
    case 'tiktok':
      return SHARE_LINKS.campaigns.tiktok;
    case 'tiktokCreator':
      return SHARE_LINKS.campaigns.tiktokCreator;
    case 'telegram':
      return SHARE_LINKS.campaigns.telegram;
    case 'beta':
    case 'general':
    default:
      return SHARE_LINKS.campaigns.beta;
  }
};

// Helper function to create share message with link
export const createShareMessage = (
  context: 'beta' | 'referral' | 'tiktok' | 'achievement' | 'transaction',
  customMessage?: string
) => {
  const baseMessage = customMessage || SHARE_LINKS.messages[context] || SHARE_LINKS.messages.beta;
  const link = context === 'tiktok' ? SHARE_LINKS.campaigns.tiktok : getShareLink(context);
  const hashtags = context === 'tiktok' ? `\n\n${SHARE_LINKS.hashtags}` : '';
  
  return `${baseMessage}${link}${hashtags}`;
};