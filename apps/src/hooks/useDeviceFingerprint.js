/**
 * React Native Hook for Device Fingerprinting
 * Provides easy integration with Confío security system
 */

import { useState, useEffect } from 'react';
import DeviceFingerprint from '../utils/deviceFingerprint';

export const useDeviceFingerprint = (options = {}) => {
  const [fingerprint, setFingerprint] = useState(null);
  const [fingerprintHash, setFingerprintHash] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const {
    generateOnMount = true,
    includeQuickFingerprint = true,
    autoRefresh = false,
    refreshInterval = 300000 // 5 minutes
  } = options;

  const generateFingerprint = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const newFingerprint = await DeviceFingerprint.generateFingerprint();
      const hash = await DeviceFingerprint.generateHash(newFingerprint);
      
      setFingerprint(newFingerprint);
      setFingerprintHash(hash);
      
      return { fingerprint: newFingerprint, hash };
    } catch (err) {
      console.error('Error generating fingerprint:', err);
      setError(err.message);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  const getQuickFingerprint = async () => {
    try {
      return await DeviceFingerprint.getQuickFingerprint();
    } catch (err) {
      console.error('Error getting quick fingerprint:', err);
      return null;
    }
  };

  const clearStoredData = async () => {
    try {
      return await DeviceFingerprint.clearStoredData();
    } catch (err) {
      console.error('Error clearing stored data:', err);
      return false;
    }
  };

  useEffect(() => {
    if (generateOnMount) {
      generateFingerprint();
    }
  }, [generateOnMount]);

  useEffect(() => {
    if (autoRefresh && refreshInterval > 0) {
      const interval = setInterval(() => {
        generateFingerprint();
      }, refreshInterval);

      return () => clearInterval(interval);
    }
  }, [autoRefresh, refreshInterval]);

  return {
    fingerprint,
    fingerprintHash,
    isLoading,
    error,
    generateFingerprint,
    getQuickFingerprint,
    clearStoredData,
    // Utility functions
    isReady: !isLoading && !error && fingerprint !== null
  };
};

export default useDeviceFingerprint;