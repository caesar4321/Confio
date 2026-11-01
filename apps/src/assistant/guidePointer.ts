// Which button the first-steps guide is pointing at. Rows register by their id,
// so the server can point at any registered row without a new build; an id
// nobody registered simply draws no pencil.
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import {
  Dimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  type ScrollView,
  type View,
} from 'react-native';
import { initialWindowMetrics } from 'react-native-safe-area-context';

// id may be empty: a sentence for this screen with nothing to circle.
export type GuidePointer = { id: string; text: string; step: string; detail?: string };
export type GuideRect = { x: number; y: number; width: number; height: number };

const SCROLL_TARGET_RATIO = 0.35;
const BACK_ARROW = 'nav_back';

const anchors = new Map<string, View>();
const listeners = new Set<() => void>();
const refreshListeners = new Set<() => void>();
let walkListener: ((key: string) => void) | null = null;
let pointer: GuidePointer | null = null;
let tapListener: ((tapped: GuidePointer) => void) | null = null;

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setGuidePointer(next: GuidePointer | null) {
  pointer = next;
  emit();
}

// The person tapped the row the pencil is circling.
export function reportGuideTap(id?: string) {
  if (id && pointer?.id === id) {
    tapListener?.(pointer);
    setGuidePointer(null);
  }
}

export function setGuideTapListener(listener: ((tapped: GuidePointer) => void) | null) {
  tapListener = listener;
}

// A screen saw the person's situation change: ask the server what comes next.
export function requestGuideRefresh() {
  refreshListeners.forEach((listener) => listener());
}

export function subscribeGuideRefresh(listener: () => void) {
  refreshListeners.add(listener);
  return () => {
    refreshListeners.delete(listener);
  };
}

// A "Muéstrame" button in the chat: the card runs the walk.
export function requestGuideWalk(key: string) {
  walkListener?.(key);
}

export function setGuideWalkListener(listener: ((key: string) => void) | null) {
  walkListener = listener;
}

export function useGuidePointer() {
  return useSyncExternalStore(subscribe, () => pointer);
}

export function measureGuideAnchor(id: string): Promise<GuideRect | null> {
  // Screens draw their own back arrow, always in this corner.
  if (id === BACK_ARROW) {
    const top = initialWindowMetrics?.insets.top ?? 0;
    return Promise.resolve({ x: 8, y: top + 6, width: 40, height: 40 });
  }
  const view = anchors.get(id);
  if (!view) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    view.measureInWindow((x, y, width, height) => resolve(width > 0 ? { x, y, width, height } : null));
  });
}

// Ref for a pressable row. Pass undefined for rows the guide never targets.
export function useGuideAnchor(id?: string) {
  const current = useRef<View | null>(null);
  return useCallback((view: View | null) => {
    if (id && !view && anchors.get(id) === current.current) {
      anchors.delete(id);
    }
    current.current = view;
    if (id && view) {
      anchors.set(id, view);
      emit();
    }
  }, [id]);
}

// Brings the pointed row into view: the card and the fold can both hide it.
export function useScrollToGuidePointer(scroll: React.RefObject<ScrollView | null>) {
  const active = useGuidePointer();
  const id = active?.id;
  const offset = useRef(0);
  useEffect(() => {
    if (!id) {
      return;
    }
    measureGuideAnchor(id).then((rect) => {
      const target = Dimensions.get('window').height * SCROLL_TARGET_RATIO;
      if (rect && rect.y > target) {
        scroll.current?.scrollTo({ y: offset.current + rect.y - target, animated: true });
      }
    });
  }, [id, scroll]);
  return useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    offset.current = event.nativeEvent.contentOffset.y;
  }, []);
}
