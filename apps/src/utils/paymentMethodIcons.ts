/**
 * Utility to map payment method icons to valid Feather icon names
 * This handles the mapping between backend icon names and react-native-vector-icons/Feather icons
 */

// Toggle verbose logging for icon resolution
const DEBUG_PAYMENT_METHOD_ICONS = false;

function debugLog(...args: any[]) {
  if (DEBUG_PAYMENT_METHOD_ICONS) {
    // eslint-disable-next-line no-console
    console.log('[PaymentMethodIcon]', ...args);
  }
}

// Map of payment method types/names to appropriate Feather icons
const PAYMENT_METHOD_ICONS: { [key: string]: string } = {
  // Banks - use credit-card or dollar-sign icons
  'bank': 'credit-card',
  'banco': 'credit-card',
  'banks': 'credit-card',
  'bancos': 'credit-card',
  
  // Specific bank names (add more as needed)
  'banco_de_venezuela': 'credit-card',
  'banco_mercantil': 'credit-card',
  'banco_provincial': 'credit-card',
  'banesco': 'credit-card',
  'banco_bicentenario': 'credit-card',
  'banco_del_tesoro': 'credit-card',
  'banco_exterior': 'credit-card',
  'banco_plaza': 'credit-card',
  'banco_caroni': 'credit-card',
  'banco_nacional_de_credito': 'credit-card',
  'banco_occidental_de_descuento': 'credit-card',
  'banco_activo': 'credit-card',
  'banco_agricola': 'credit-card',
  'banco_fondo_comun': 'credit-card',
  'banco_sofitasa': 'credit-card',
  'banco_100_porciento_banco': 'credit-card',
  
  // Fintech/Digital payment methods
  'pago_movil': 'smartphone',
  'pago_móvil': 'smartphone',
  'mobile_payment': 'smartphone',
  'pagomovil': 'smartphone',
  
  // Digital wallets
  'paypal': 'dollar-sign',
  'zelle': 'send',
  'wally': 'smartphone',
  'venmo': 'dollar-sign',
  'cashapp': 'dollar-sign',
  'binance': 'trending-up',
  'binance_pay': 'trending-up',
  
  // Cash
  'efectivo': 'dollar-sign',
  'cash': 'dollar-sign',
  'dinero_efectivo': 'dollar-sign',
  
  // Transfers
  'transferencia': 'repeat',
  'transfer': 'repeat',
  'wire_transfer': 'repeat',
  'transferencia_bancaria': 'repeat',
  'bank_transfer': 'repeat',
  
  // Default fallback
  'default': 'credit-card'
};

/**
 * Get the appropriate Feather icon name for a payment method
 * @param icon - The icon name from the backend
 * @param providerType - The provider type (bank, fintech, etc.)
 * @param displayName - The display name of the payment method
 * @returns A valid Feather icon name
 */
export function getPaymentMethodIcon(
  icon?: string | null, 
  providerType?: string | null,
  displayName?: string | null
): string {
  // Debug logging (gated)
  debugLog('Input:', { icon, providerType, displayName });
  
  // First try to use the provided icon if it's valid
  if (icon && isValidFeatherIcon(icon)) {
    debugLog('Using provided valid icon:', icon);
    return icon;
  }
  
  // If icon is provided but not valid, log it for debugging
  if (icon) {
    debugLog('Invalid icon provided:', icon);
  }
  
  // Try to match by icon name (normalized)
  if (icon) {
    const normalizedIcon = normalizeKey(icon);
    if (PAYMENT_METHOD_ICONS[normalizedIcon]) {
      debugLog('Using normalized icon mapping:', PAYMENT_METHOD_ICONS[normalizedIcon]);
      return PAYMENT_METHOD_ICONS[normalizedIcon];
    }
  }
  
  // Try to match by provider type first (more reliable than display name)
  if (providerType) {
    const normalizedType = normalizeKey(providerType);
    if (PAYMENT_METHOD_ICONS[normalizedType]) {
      debugLog('Using provider type mapping:', PAYMENT_METHOD_ICONS[normalizedType]);
      return PAYMENT_METHOD_ICONS[normalizedType];
    }
  }
  
  // Default fallback based on provider type (most important for banks)
  if (providerType?.toLowerCase() === 'bank') {
    debugLog('Using bank fallback: credit-card');
    return 'credit-card';
  }
  if (providerType?.toLowerCase() === 'fintech') {
    debugLog('Using fintech fallback: smartphone');
    return 'smartphone';
  }
  
  // Try to match by display name as last resort
  if (displayName) {
    const normalizedName = normalizeKey(displayName);
    
    // Check if it contains any known patterns
    for (const [pattern, iconName] of Object.entries(PAYMENT_METHOD_ICONS)) {
      if (normalizedName.includes(pattern) || pattern.includes(normalizedName)) {
        debugLog('Using display name pattern match:', iconName);
        return iconName;
      }
    }
    
    // Check for common patterns
    if (normalizedName.includes('banco') || normalizedName.includes('bank')) {
      debugLog('Using banco/bank pattern: credit-card');
      return 'credit-card';
    }
    if (normalizedName.includes('pago') && normalizedName.includes('movil')) {
      debugLog('Using pago movil pattern: smartphone');
      return 'smartphone';
    }
    if (normalizedName.includes('efectivo') || normalizedName.includes('cash')) {
      debugLog('Using cash pattern: dollar-sign');
      return 'dollar-sign';
    }
    if (normalizedName.includes('transfer')) {
      debugLog('Using transfer pattern: repeat');
      return 'repeat';
    }
  }
  
  // Ultimate fallback
  debugLog('Using ultimate fallback:', PAYMENT_METHOD_ICONS.default);
  return PAYMENT_METHOD_ICONS.default;
}

/**
 * Normalize a string key for matching
 */
function normalizeKey(key: string): string {
  return key
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_')
    .replace(/[áàäâ]/g, 'a')
    .replace(/[éèëê]/g, 'e')
    .replace(/[íìïî]/g, 'i')
    .replace(/[óòöô]/g, 'o')
    .replace(/[úùüû]/g, 'u')
    .replace(/ñ/g, 'n')
    .replace(/[^a-z0-9_]/g, '');
}

/**
 * Check if an icon name is a valid Feather icon
 * This is a subset of common Feather icons we use in the app
 */
function isValidFeatherIcon(iconName: string): boolean {
  const validIcons = [
    'credit-card',
    'dollar-sign',
    'smartphone',
    'send',
    'repeat',
    'trending-up',
    'activity',
    'airplay',
    'alert-circle',
    'alert-octagon',
    'alert-triangle',
    'align-center',
    'align-justify',
    'align-left',
    'align-right',
    'anchor',
    'aperture',
    'archive',
    'arrow-down',
    'arrow-down-circle',
    'arrow-down-left',
    'arrow-down-right',
    'arrow-left',
    'arrow-left-circle',
    'arrow-right',
    'arrow-right-circle',
    'arrow-up',
    'arrow-up-circle',
    'arrow-up-left',
    'arrow-up-right',
    'at-sign',
    'award',
    'bar-chart',
    'bar-chart-2',
    'battery',
    'battery-charging',
    'bell',
    'bell-off',
    'bluetooth',
    'bold',
    'book',
    'book-open',
    'bookmark',
    'box',
    'briefcase',
    'calendar',
    'camera',
    'camera-off',
    'cast',
    'check',
    'check-circle',
    'check-square',
    'chevron-down',
    'chevron-left',
    'chevron-right',
    'chevron-up',
    'chevrons-down',
    'chevrons-left',
    'chevrons-right',
    'chevrons-up',
    'chrome',
    'circle',
    'clipboard',
    'clock',
    'cloud',
    'cloud-drizzle',
    'cloud-lightning',
    'cloud-off',
    'cloud-rain',
    'cloud-snow',
    'code',
    'codepen',
    'codesandbox',
    'coffee',
    'columns',
    'command',
    'compass',
    'copy',
    'corner-down-left',
    'corner-down-right',
    'corner-left-down',
    'corner-left-up',
    'corner-right-down',
    'corner-right-up',
    'corner-up-left',
    'corner-up-right',
    'cpu',
    'crop',
    'crosshair',
    'database',
    'delete',
    'disc',
    'divide',
    'divide-circle',
    'divide-square',
    'download',
    'download-cloud',
    'dribbble',
    'droplet',
    'edit',
    'edit-2',
    'edit-3',
    'external-link',
    'eye',
    'eye-off',
    'facebook',
    'fast-forward',
    'feather',
    'figma',
    'file',
    'file-minus',
    'file-plus',
    'file-text',
    'film',
    'filter',
    'flag',
    'folder',
    'folder-minus',
    'folder-plus',
    'framer',
    'frown',
    'gift',
    'git-branch',
    'git-commit',
    'git-merge',
    'git-pull-request',
    'github',
    'gitlab',
    'globe',
    'grid',
    'hard-drive',
    'hash',
    'headphones',
    'heart',
    'help-circle',
    'hexagon',
    'home',
    'image',
    'inbox',
    'info',
    'instagram',
    'italic',
    'key',
    'layers',
    'layout',
    'life-buoy',
    'link',
    'link-2',
    'linkedin',
    'list',
    'loader',
    'lock',
    'log-in',
    'log-out',
    'mail',
    'map',
    'map-pin',
    'maximize',
    'maximize-2',
    'meh',
    'menu',
    'message-circle',
    'message-square',
    'mic',
    'mic-off',
    'minimize',
    'minimize-2',
    'minus',
    'minus-circle',
    'minus-square',
    'monitor',
    'moon',
    'more-horizontal',
    'more-vertical',
    'mouse-pointer',
    'move',
    'music',
    'navigation',
    'navigation-2',
    'octagon',
    'package',
    'paperclip',
    'pause',
    'pause-circle',
    'pen-tool',
    'percent',
    'phone',
    'phone-call',
    'phone-forwarded',
    'phone-incoming',
    'phone-missed',
    'phone-off',
    'phone-outgoing',
    'pie-chart',
    'play',
    'play-circle',
    'plus',
    'plus-circle',
    'plus-square',
    'pocket',
    'power',
    'printer',
    'radio',
    'refresh-ccw',
    'refresh-cw',
    'rewind',
    'rotate-ccw',
    'rotate-cw',
    'rss',
    'save',
    'scissors',
    'search',
    'server',
    'settings',
    'share',
    'share-2',
    'shield',
    'shield-off',
    'shopping-bag',
    'shopping-cart',
    'shuffle',
    'sidebar',
    'skip-back',
    'skip-forward',
    'slack',
    'slash',
    'sliders',
    'smile',
    'speaker',
    'square',
    'star',
    'stop-circle',
    'sun',
    'sunrise',
    'sunset',
    'tablet',
    'tag',
    'target',
    'terminal',
    'thermometer',
    'thumbs-down',
    'thumbs-up',
    'toggle-left',
    'toggle-right',
    'tool',
    'trash',
    'trash-2',
    'trello',
    'trending-down',
    'triangle',
    'truck',
    'tv',
    'twitch',
    'twitter',
    'type',
    'umbrella',
    'underline',
    'unlock',
    'upload',
    'upload-cloud',
    'user',
    'user-check',
    'user-minus',
    'user-plus',
    'user-x',
    'users',
    'video',
    'video-off',
    'voicemail',
    'volume',
    'volume-1',
    'volume-2',
    'volume-x',
    'watch',
    'wifi',
    'wifi-off',
    'wind',
    'x',
    'x-circle',
    'x-octagon',
    'x-square',
    'youtube',
    'zap',
    'zap-off',
    'zoom-in',
    'zoom-out'
  ];
  
  return validIcons.includes(iconName);
}
