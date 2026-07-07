import React, { useEffect, useRef, useState } from 'react';
import { fmtAmount } from './landingStats';

// Tick-settle — the site's single motion signature (DESIGN.md):
// money figures roll in softly (~1.2s ease-out cubic, triggered once on
// view) and settle with a brief emerald pulse.
//
// Resilience rules (adversarial review):
// - Browsers without IntersectionObserver/matchMedia (old Android
//   WebViews) get the final value immediately — never a crash.
// - Rolling writes go straight to the DOM node (no per-frame React
//   re-renders); React state changes only on settle.
// - A value change mid-flight (Apollo cache-and-network delivering a
//   fresher number) re-rolls FROM the currently displayed value, not
//   from zero, and re-arms the settle pulse.
const TickerNumber = ({ value, decimals = 0, prefix = 'US$', className }) => {
  const ref = useRef(null);
  const currentRef = useRef(0); // last value painted, roll-from-here on updates
  const [settled, setSettled] = useState(false);

  const fmt = (n) => fmtAmount(n, decimals, prefix);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    setSettled(false);

    const finish = () => {
      currentRef.current = value;
      node.textContent = fmt(value);
      setSettled(true);
    };

    const noAnimationSupport =
      typeof window.IntersectionObserver === 'undefined' ||
      typeof window.matchMedia !== 'function' ||
      typeof window.requestAnimationFrame !== 'function';
    if (noAnimationSupport || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      finish();
      return undefined;
    }

    let raf;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) return;
        observer.disconnect();
        const from = currentRef.current;
        const duration = 1200;
        const start = performance.now();
        const frame = (now) => {
          const t = Math.min((now - start) / duration, 1);
          const eased = 1 - Math.pow(1 - t, 3);
          const current = from + (value - from) * eased;
          currentRef.current = current;
          node.textContent = fmt(current);
          if (t < 1) {
            raf = requestAnimationFrame(frame);
          } else {
            finish();
          }
        };
        raf = requestAnimationFrame(frame);
      },
      { threshold: 0.4 }
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [value, decimals, prefix]);

  return (
    <span ref={ref} className={className} data-settled={settled || undefined}>
      {fmt(settled ? value : currentRef.current)}
    </span>
  );
};

export default TickerNumber;
