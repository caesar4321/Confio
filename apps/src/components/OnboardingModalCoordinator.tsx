import React, { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useQuery } from '@apollo/client';
import { GET_ME } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { ConfioIcpModal } from './ConfioIcpModal';
import { ConfioRatingModal } from './ConfioRatingModal';

/**
 * Server-driven modal coordinator. Reads `me.pendingModal` and renders at most
 * one modal at a time — ICP > RATING > NONE — per the server's priority.
 *
 * IMPORTANT: only the active modal is mounted. Rendering two RN <Modal>
 * siblings (one visible, one hidden) on Android can leave a phantom native
 * window that intercepts touches on the visible one.
 */
export const OnboardingModalCoordinator: React.FC = () => {
    const { isAuthenticated } = useAuth();
    const { data, refetch } = useQuery(GET_ME, {
        skip: !isAuthenticated,
        fetchPolicy: 'cache-and-network',
    });

    // refetch is a new function reference each render; keep it in a ref so the
    // AppState listener can read the latest without rebinding on every Apollo
    // cache update.
    const refetchRef = useRef(refetch);
    refetchRef.current = refetch;

    useEffect(() => {
        if (!isAuthenticated) return;
        const sub = AppState.addEventListener('change', state => {
            if (state === 'active') {
                refetchRef.current().catch(() => { });
            }
        });
        return () => sub.remove();
    }, [isAuthenticated]);

    if (!isAuthenticated) return null;

    const pending = data?.me?.pendingModal ?? 'NONE';
    const onClose = () => refetchRef.current().catch(() => { });

    if (pending === 'ICP') {
        return <ConfioIcpModal visible onClose={onClose} />;
    }
    if (pending === 'RATING') {
        return <ConfioRatingModal visible onClose={onClose} />;
    }
    return null;
};
