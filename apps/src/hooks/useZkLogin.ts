import { useState, useCallback } from 'react';
import { AuthService } from '../services/authService';

export const useZkLogin = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [zkLoginData, setZkLoginData] = useState<any>(null);

  const signInWithGoogle = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const authService = AuthService.getInstance();
      const result = await authService.signInWithGoogle();
      setZkLoginData(result);
      return result;
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const signInWithApple = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const authService = AuthService.getInstance();
      const result = await authService.signInWithApple();
      setZkLoginData(result);
      return result;
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const authService = AuthService.getInstance();
      await authService.signOut();
      setZkLoginData(null);
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    loading,
    error,
    zkLoginData,
    signInWithGoogle,
    signInWithApple,
    signOut
  };
}; 