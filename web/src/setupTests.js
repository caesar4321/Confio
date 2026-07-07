// Auto-loaded by react-scripts before every test suite.
import '@testing-library/jest-dom';

// jsdom lacks matchMedia. Default: no media query matches (i.e. no
// prefers-reduced-motion). Tests that need reduced motion reassign
// window.matchMedia in their own beforeEach/test body — the global
// beforeEach below resets it so overrides never leak between tests.
export const createMatchMedia = (matches) => (query) => ({
  matches: typeof matches === 'function' ? matches(query) : matches,
  media: query,
  onchange: null,
  addListener: jest.fn(),
  removeListener: jest.fn(),
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  dispatchEvent: jest.fn(),
});

// jsdom lacks IntersectionObserver (used by TickerNumber and
// react-intersection-observer). Default is a no-op observer; tests that
// need to fire intersections install their own capturing mock.
class NoopIntersectionObserver {
  constructor() {
    this.root = null;
    this.rootMargin = '';
    this.thresholds = [];
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

beforeEach(() => {
  window.matchMedia = jest.fn(createMatchMedia(false));
  window.IntersectionObserver = NoopIntersectionObserver;
  global.IntersectionObserver = NoopIntersectionObserver;
});
