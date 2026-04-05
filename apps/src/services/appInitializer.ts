import ContactService from './contactService';

/**
 * Initialize app services early for better performance
 */
export const initializeApp = () => {  const startTime = Date.now();
  
  // Initialize ContactService asynchronously to avoid blocking UI
  setTimeout(() => {
    ContactService.getInstance();  }, 100); // Small delay to ensure UI is responsive  
  // Add other service initializations here as needed
};
