/**
 * Global notification deduplication service
 * Prevents duplicate notifications across multiple JS contexts in React Native
 */

// Use a global variable that persists across all VMs
declare global {
  var __notificationCache: {
    processedIds: Set<string>;
    lastCleanup: number;
  } | undefined;
}

const CACHE_DURATION = 60 * 1000; // 1 minute
const CLEANUP_INTERVAL = 5 * 60 * 1000; // 5 minutes

export class NotificationDeduplication {
  private static instance: NotificationDeduplication;

  private constructor() {
    // Initialize global cache if not exists
    if (!global.__notificationCache) {
      global.__notificationCache = {
        processedIds: new Set<string>(),
        lastCleanup: Date.now()
      };
    }
  }

  static getInstance(): NotificationDeduplication {
    if (!NotificationDeduplication.instance) {
      NotificationDeduplication.instance = new NotificationDeduplication();
    }
    return NotificationDeduplication.instance;
  }

  /**
   * Check if a notification has already been processed
   * @param messageId - The unique message ID from Firebase
   * @param notificationId - The notification ID from our backend
   * @returns true if this is a duplicate notification
   */
  isDuplicate(messageId?: string, notificationId?: string): boolean {
    const cache = global.__notificationCache!;
    
    // Cleanup old entries periodically
    if (Date.now() - cache.lastCleanup > CLEANUP_INTERVAL) {
      this.cleanup();
    }

    // Create composite key from available IDs
    const keys: string[] = [];
    if (messageId) keys.push(`msg_${messageId}`);
    if (notificationId) keys.push(`notif_${notificationId}`);
    
    // If no keys available, can't deduplicate
    if (keys.length === 0) {
      console.log(`[NotificationDedup] No IDs available for deduplication`);
      return false;
    }
    
    // Check if any key exists in cache
    for (const key of keys) {
      if (cache.processedIds.has(key)) {
        console.log(`[NotificationDedup] Duplicate detected: ${key}`);
        return true;
      }
    }

    console.log(`[NotificationDedup] New notification, adding keys:`, keys);
    
    // Add all keys to cache
    for (const key of keys) {
      cache.processedIds.add(key);
      // Schedule removal after cache duration
      setTimeout(() => {
        cache.processedIds.delete(key);
      }, CACHE_DURATION);
    }

    return false;
  }

  /**
   * Manually add a notification to the processed set
   */
  markAsProcessed(messageId?: string, notificationId?: string): void {
    const cache = global.__notificationCache!;
    
    if (messageId) {
      const key = `msg_${messageId}`;
      cache.processedIds.add(key);
      setTimeout(() => cache.processedIds.delete(key), CACHE_DURATION);
    }
    
    if (notificationId) {
      const key = `notif_${notificationId}`;
      cache.processedIds.add(key);
      setTimeout(() => cache.processedIds.delete(key), CACHE_DURATION);
    }
  }

  /**
   * Clean up old entries
   */
  private cleanup(): void {
    const cache = global.__notificationCache!;
    // In a production app, you'd want to track timestamps for each entry
    // For now, we'll just clear the cache if it gets too large
    if (cache.processedIds.size > 1000) {
      cache.processedIds.clear();
    }
    cache.lastCleanup = Date.now();
  }

  /**
   * Clear all cached notifications (useful for testing)
   */
  clearCache(): void {
    const cache = global.__notificationCache!;
    cache.processedIds.clear();
    cache.lastCleanup = Date.now();
  }
}

export default NotificationDeduplication.getInstance();