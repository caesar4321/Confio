import React, { useEffect } from 'react';
import { AppState } from 'react-native';
import { useQuery } from '@apollo/client';
import { GET_ME } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { ConfioIcpModal } from './ConfioIcpModal';
import { ConfioRatingModal } from './ConfioRatingModal';

/**
 * Server-driven modal coordinator. Reads `me.pendingModal` and renders at most
 * one modal at a time — ICP > RATING > NONE — per the server's priority. No
 * client-side queueing; we just react to whatever the server reports next.
 */
export const OnboardingModalCoordinator: React.FC = () => {
    const { isAuthenticated } = useAuth();
    const { data, refetch } = useQuery(GET_ME, {
        skip: !isAuthenticated,
        fetchPolicy: 'cache-and-network',
    });

    useEffect(() => {
        if (!isAuthenticated) return;
        const sub = AppState.addEventListener('change', state => {
            if (state === 'active') {
                refetch().catch(() => { });
            }
        });
        return () => sub.remove();
    }, [isAuthenticated, refetch]);

    if (!isAuthenticated) return null;

    const pending = data?.me?.pendingModal ?? 'NONE';

    return (
        <>
            <ConfioIcpModal visible={pending === 'ICP'} onClose={() => refetch().catch(() => { })} />
            <ConfioRatingModal visible={pending === 'RATING'} onClose={() => refetch().catch(() => { })} />
        </>
    );
};
