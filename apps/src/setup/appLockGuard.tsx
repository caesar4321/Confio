import React, { forwardRef, useSyncExternalStore } from 'react';

/**
 * The resume lock keeps Main mounted so unlocking lands exactly where the user
 * was. Native Modals and Alerts draw above every React Native view, lock screen
 * included, so a screen that stays mounted could otherwise put wallet content
 * or a working button above the lock:
 * - every Modal is hidden while locked. The owner keeps its `visible` state, so
 *   it comes back on unlock (state inside the Modal's children does not: iOS
 *   cannot present the lock over a Modal, so the Modal has to go).
 * - every Alert waits for the unlock, and is dropped if the session ends.
 *
 * Installed over the `react-native` exports so that nothing in the app, present
 * or future, can forget this.
 */
// require, not `import *`: that yields a copy, and the override must land on
// the module every `import { Modal }` reads from.
const ReactNative = require('react-native');
const OriginalModal: typeof import('react-native').Modal = ReactNative.Modal;
const AlertModule: typeof import('react-native').Alert = ReactNative.Alert;
const originalAlert = AlertModule.alert;

let locked = false;
let allowAlert = false;
let heldAlerts: Parameters<typeof originalAlert>[] = [];
const listeners = new Set<() => void>();

export function setAppLocked(next: boolean, options?: { dropHeldAlerts?: boolean }) {
  if (locked === next) return;
  locked = next;
  listeners.forEach(listener => listener());
  if (next) return;
  const held = heldAlerts;
  heldAlerts = [];
  if (!options?.dropHeldAlerts) held.forEach(args => originalAlert(...args));
}

/** For the lock's own dialogs, and for news that must outlive the session. */
export function alertAboveLock(...args: Parameters<typeof originalAlert>) {
  allowAlert = true;
  try {
    AlertModule.alert(...args);
  } finally {
    allowAlert = false;
  }
}

AlertModule.alert = (...args) => {
  if (locked && !allowAlert) {
    heldAlerts.push(args);
    return;
  }
  originalAlert(...args);
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
const getLocked = () => locked;

type ModalProps = React.ComponentProps<typeof OriginalModal>;

export const LockAwareModal = forwardRef<any, ModalProps>((props, ref) => {
  const isLocked = useSyncExternalStore(subscribe, getLocked);
  return (
    <OriginalModal
      {...props}
      ref={ref}
      visible={props.visible !== false && !isLocked}
      // Hiding for the lock is not the user dismissing it.
      onDismiss={isLocked ? undefined : props.onDismiss}
    />
  );
});
LockAwareModal.displayName = 'Modal';

Object.defineProperty(ReactNative, 'Modal', {
  configurable: true,
  enumerable: true,
  value: LockAwareModal,
});
