import ContactService from './contactService';

/**
 * Initialize app services early for better performance
 */
export const initializeApp = () => {
  console.log('[PERF] App initialization started');
  const startTime = Date.now();
  
  // Initialize ContactService asynchronously to avoid blocking UI
  setTimeout(() => {
    ContactService.getInstance();
    console.log(`[PERF] ContactService initialized after ${Date.now() - startTime}ms`);
  }, 100); // Small delay to ensure UI is responsive
  
  console.log(`[PERF] App initialization setup completed in ${Date.now() - startTime}ms`);
  
  // Add other service initializations here as needed
};