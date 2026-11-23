// The purchases a chat message carries. Each purchase is drawn once in the
// conversation, under the newest message that carries it, and updates there.
// The card itself (and its GraphQL documents) loads only when one is shown.
import React, { useEffect, useSyncExternalStore } from 'react';

import { latestCardFor, onCards, showCard, taskActions } from './helpers';

type Action = { type: string; target?: string | null };

export function PurchaseCards({ actions, messageId, createdAt, onStores }: {
  actions: Action[]; messageId: string; createdAt: string; onStores?: () => void;
}) {
  const ids = taskActions(actions);
  if (!ids.length) {
    return null;
  }
  return (
    <>
      {ids.map((taskId) => (
        <Slot key={taskId} taskId={taskId} messageId={messageId} at={Date.parse(createdAt) || 0} onStores={onStores} />
      ))}
    </>
  );
}

function Slot({ taskId, messageId, at, onStores }: {
  taskId: string; messageId: string; at: number; onStores?: () => void;
}) {
  useEffect(() => showCard(taskId, messageId, at), [taskId, messageId, at]);
  const latest = useSyncExternalStore(onCards, () => latestCardFor(taskId));
  if (latest !== messageId) {
    return null;
  }
  const { PurchaseCard } = require('./PurchaseCard');
  return <PurchaseCard taskId={taskId} onStores={onStores} />;
}
