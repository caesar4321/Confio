// The purchases a chat message carries. Each purchase is drawn once in the
// conversation, under the newest message that carries it, and updates there.
// The card itself (and its GraphQL documents) loads only when one is shown.
import React, { useEffect, useSyncExternalStore } from 'react';

import { latestCardFor, offersActions, onCards, showCard, taskActions } from './helpers';

type Action = { type: string; target?: string | null };

// `onOpen` closes the chat and opens one of the app's screens (a local account to open).
type Open = (screen: string, params?: Record<string, unknown>) => void;

export function PurchaseCards({ actions, messageId, createdAt, onStores, onOpen }: {
  actions: Action[]; messageId: string; createdAt: string; onStores?: () => void; onOpen?: Open;
}) {
  const ids = taskActions(actions);
  const searches = offersActions(actions);
  if (!ids.length && !searches.length) {
    return null;
  }
  return (
    <>
      {searches.map((offersId) => {
        // Loaded only when a search across stores is shown.
        const { OffersCard } = require('./OffersCard');
        return <OffersCard key={offersId} offersId={offersId} />;
      })}
      {ids.map((taskId) => (
        <Slot key={taskId} taskId={taskId} messageId={messageId} at={Date.parse(createdAt) || 0} onStores={onStores}
          onOpen={onOpen} />
      ))}
    </>
  );
}

function Slot({ taskId, messageId, at, onStores, onOpen }: {
  taskId: string; messageId: string; at: number; onStores?: () => void; onOpen?: Open;
}) {
  useEffect(() => showCard(taskId, messageId, at), [taskId, messageId, at]);
  const latest = useSyncExternalStore(onCards, () => latestCardFor(taskId));
  if (latest !== messageId) {
    return null;
  }
  const { PurchaseCard } = require('./PurchaseCard');
  return <PurchaseCard taskId={taskId} onStores={onStores} onOpen={onOpen} />;
}
