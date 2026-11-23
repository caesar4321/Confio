// What the conversation home's header and drawer show about the person's
// money. HomeScreen (mounted unseen inside the conversation home) is the only writer:
// it already reads every balance and owns the rules for what counts and what
// is hidden, so the header, the drawer and the full list can never disagree.
import { createContext, useContext, useSyncExternalStore } from 'react';
import type { HeroMonthState } from '../hooks/useMonthHeroLine';

export type HomeMoneyTile = {
  key: string;
  label: string;
  /** Formatted and already masked; null = an offer tile (no amount). */
  amount: string | null;
  /** Drawn dashed, with `offerLabel` where the amount would be. */
  offerLabel?: string;
  accessibilityLabel: string;
  onPress: () => void;
};

export type HomeMoneyAction = {
  id: 'send' | 'receive';
  label: string;
  icon: string;
  filled: boolean;
  onPress: () => void;
};

/** An account the person can switch to, as the menu lists it. */
export type HomeAccount = {
  id: string;
  name: string;
  /** "Personal", "Negocio", "Empleado · Cajero", "Tu cuenta"… */
  kind: string;
  avatar: string;
  selected: boolean;
};

/** Money or a task waiting on the person: one line above the composer. */
export type HomeMoneyNotice = {
  key: string;
  icon: string;
  text: string;
  onPress: () => void;
};

export type HomeMoney = {
  /** False until the first balances answer: nothing is drawn as US$0. */
  ready: boolean;
  /** Formatted total with its currency sign (US$, or the local currency the
   * person switched to), or the mask. */
  total: string;
  masked: boolean;
  /** Employees without viewBalance never get the eye. */
  canToggle: boolean;
  toggleBalance: () => void;
  /** The currency the total is shown in ("USD", "BOB"); null where there is
   * no local currency to switch to. */
  currencyCode: string | null;
  /** What the switch does next, for a screen reader ("Mostrar en bolivianos"). */
  currencyHint: string;
  toggleCurrency: () => void;
  /** Ask for the balances again (the menu does when it opens). */
  refresh: () => void;
  /** Every account of this person, the current one marked. */
  accounts: HomeAccount[];
  switchAccount: (id: string) => void;
  createBusiness: () => void;
  month: HeroMonthState;
  openMonth: () => void;
  tiles: HomeMoneyTile[];
  /** Opens the Cuenta inteligente (or its offer); null for accounts that never see it. */
  openSmart?: (() => void) | null;
  actions: HomeMoneyAction[];
  notice: HomeMoneyNotice | null;
};

const EMPTY: HomeMoney = {
  ready: false,
  total: '',
  masked: false,
  canToggle: false,
  toggleBalance: () => {},
  currencyCode: null,
  currencyHint: '',
  toggleCurrency: () => {},
  refresh: () => {},
  accounts: [],
  switchAccount: () => {},
  createBusiness: () => {},
  month: { kind: 'hidden' },
  openMonth: () => {},
  tiles: [],
  openSmart: null,
  actions: [],
  notice: null,
};

// One store per home shell. Older screens still reach the tabs with a plain
// `navigate('BottomTabs')` from a pushed screen, which stacks a second shell
// on top of the first (React Navigation 7); each has its own home, drawer
// and figures, and one going away never touches the other's.
export type HomeMoneyStore = {
  get: () => HomeMoney;
  /** Publishing the same snapshot again notifies nobody. */
  publish: (next: HomeMoney) => void;
  reset: () => void;
  subscribe: (listener: () => void) => () => void;
};

export function createHomeMoneyStore(): HomeMoneyStore {
  let current: HomeMoney = EMPTY;
  const listeners = new Set<() => void>();
  const publish = (next: HomeMoney) => {
    if (next === current) {
      return;
    }
    current = next;
    listeners.forEach((l) => l());
  };
  return {
    get: () => current,
    publish,
    reset: () => publish(EMPTY),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

// Outside a shell (a test, a screen mounted on its own): one shared store.
export const sharedHomeMoneyStore = createHomeMoneyStore();
const HomeMoneyStoreContext = createContext<HomeMoneyStore>(sharedHomeMoneyStore);

/** The drawer provider gives its shell a store through this. */
export const HomeMoneyStoreProvider = HomeMoneyStoreContext.Provider;

export function useHomeMoneyStore(): HomeMoneyStore {
  return useContext(HomeMoneyStoreContext);
}

export function useHomeMoney(): HomeMoney {
  const store = useHomeMoneyStore();
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

// The menu can be asked for from outside React (the assistant's `home`
// destination: "muéstrame mi dinero"). Every mounted shell registers how to
// open its own; the newest one, which is the one on top, answers.
const menus: (() => void)[] = [];

/** Returns its own undo. */
export function registerHomeMenu(open: () => void): () => void {
  menus.push(open);
  return () => {
    const at = menus.indexOf(open);
    if (at >= 0) {
      menus.splice(at, 1);
    }
  };
}

// The wallets can be opened from outside React too (the assistant's
// `wallet_dollar` / `wallet_confio`): the shell on top lends its snapshot.
const readers: (() => HomeMoney)[] = [];

/** Returns its own undo. */
export function registerHomeMoneyReader(read: () => HomeMoney): () => void {
  readers.push(read);
  return () => {
    const at = readers.indexOf(read);
    if (at >= 0) {
      readers.splice(at, 1);
    }
  };
}

/** Opens that wallet as its tile in the menu does; false when it is not there to open. */
export function requestHomeTile(key: string): boolean {
  const tile = readers[readers.length - 1]?.().tiles.find((t) => t.key === key);
  if (!tile) {
    return false;
  }
  tile.onPress();
  return true;
}

/** True if a conversation home is mounted to show it. */
export function requestHomeMenu(): boolean {
  const top = menus[menus.length - 1];
  if (!top) {
    return false;
  }
  top();
  return true;
}
