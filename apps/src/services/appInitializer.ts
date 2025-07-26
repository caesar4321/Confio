import ContactService from './contactService';

/**
 * Initialize app services early for better performance
 */
export const initializeApp = () => {
  console.log('[PERF] App initialization started');
  const startTime = Date.now();
  
  // Initialize ContactService immediately to preload contacts
  ContactService.getInstance();
  
  console.log(`[PERF] App initialization completed in ${Date.now() - startTime}ms`);
  
  // Add other service initializations here as needed
};