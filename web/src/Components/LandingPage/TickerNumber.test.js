import React from 'react';
import { render, screen, act } from '@testing-library/react';
import TickerNumber from './TickerNumber';
import { createMatchMedia } from '../../setupTests';

// Capturing IntersectionObserver mock — lets tests fire the intersection
// that starts the odometer roll.
class MockIntersectionObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.disconnected = false;
    MockIntersectionObserver.instances.push(this);
  }
  observe(el) {
    this.element = el;
  }
  unobserve() {}
  disconnect() {
    this.disconnected = true;
  }
}
MockIntersectionObserver.instances = [];

describe('TickerNumber', () => {
  let rafQueue;
  let now;
  let cancelSpy;

  beforeEach(() => {
    MockIntersectionObserver.instances = [];
    window.IntersectionObserver = MockIntersectionObserver;
    global.IntersectionObserver = MockIntersectionObserver;

    // Deterministic clock + synchronously-drainable rAF queue.
    now = 0;
    rafQueue = [];
    jest.spyOn(performance, 'now').mockImplementation(() => now);
    jest
      .spyOn(window, 'requestAnimationFrame')
      .mockImplementation((cb) => rafQueue.push(cb));
    cancelSpy = jest
      .spyOn(window, 'cancelAnimationFrame')
      .mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  const intersect = (isIntersecting = true) => {
    const observer = MockIntersectionObserver.instances.at(-1);
    act(() => observer.callback([{ isIntersecting }]));
    return observer;
  };

  // Drain queued animation frames, advancing the mocked clock to
  // `timestamp` for each drain pass.
  const runFrames = (timestamp) => {
    now = timestamp;
    const cbs = rafQueue.splice(0);
    act(() => {
      cbs.forEach((cb) => cb(timestamp));
    });
  };

  it('renders US$0 before entering the viewport, without data-settled', () => {
    render(<TickerNumber value={9800} />);
    const el = screen.getByText('US$0');
    expect(el).not.toHaveAttribute('data-settled');
    expect(rafQueue).toHaveLength(0);
  });

  it('does not start rolling on a non-intersecting entry', () => {
    render(<TickerNumber value={9800} />);
    const observer = intersect(false);
    expect(rafQueue).toHaveLength(0);
    expect(observer.disconnected).toBe(false);
    expect(screen.getByText('US$0')).toBeInTheDocument();
  });

  it('rolls with ease-out cubic and settles on the exact final value', () => {
    render(<TickerNumber value={1000} />);
    const observer = intersect();
    // Observer fires once, then disconnects so the roll never re-triggers.
    expect(observer.disconnected).toBe(true);
    expect(rafQueue).toHaveLength(1);

    // Halfway (t=0.5): eased = 1 - 0.5^3 = 0.875 → 875.
    runFrames(600);
    const el = screen.getByText('US$875');
    expect(el).not.toHaveAttribute('data-settled');

    // End of the 1.2s roll: exact value, settled, no more frames queued.
    runFrames(1200);
    expect(screen.getByText('US$1,000')).toHaveAttribute('data-settled', 'true');
    expect(rafQueue).toHaveLength(0);
  });

  it('clamps past-duration timestamps to the final value', () => {
    render(<TickerNumber value={52642} />);
    intersect();
    runFrames(5000); // way past 1200ms — t clamps to 1
    expect(screen.getByText('US$52,642')).toHaveAttribute('data-settled', 'true');
  });

  it('formats with decimals and a custom prefix during and after the roll', () => {
    render(<TickerNumber value={1234.56} decimals={2} prefix="$" />);
    intersect();
    runFrames(1200);
    expect(screen.getByText('$1,234.56')).toHaveAttribute('data-settled', 'true');
  });

  it('skips the animation entirely under prefers-reduced-motion', () => {
    window.matchMedia = jest.fn(
      createMatchMedia((query) => query.includes('prefers-reduced-motion'))
    );
    render(<TickerNumber value={125431} />);
    // Final formatted value immediately, settled, no observer, no frames.
    expect(screen.getByText('US$125,431')).toHaveAttribute('data-settled', 'true');
    expect(MockIntersectionObserver.instances).toHaveLength(0);
    expect(rafQueue).toHaveLength(0);
  });

  it('cancels the pending frame and disconnects on unmount mid-roll', () => {
    const { unmount } = render(<TickerNumber value={1000} />);
    const observer = intersect();
    runFrames(600); // mid-roll, another frame is queued
    expect(rafQueue).toHaveLength(1);
    expect(() => unmount()).not.toThrow();
    expect(cancelSpy).toHaveBeenCalled();
    expect(observer.disconnected).toBe(true);
  });
});
