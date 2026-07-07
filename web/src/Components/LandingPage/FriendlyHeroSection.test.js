import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyHeroSection from './FriendlyHeroSection';
import { LANDING_STATS } from './landingStats';
import { LanguageProvider } from '../../contexts/LanguageContext';
import { createMatchMedia } from '../../setupTests';

// jsdom's navigator.language is en-US, so LanguageProvider resolves to
// English copy — assertions below use the English labels.
const renderHero = (mocks, props = {}) =>
  render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <LanguageProvider>
        <FriendlyHeroSection {...props} />
      </LanguageProvider>
    </MockedProvider>
  );

const statsMock = (landingStats) => ({
  request: { query: LANDING_STATS },
  result: { data: { landingStats } },
});

const flushQuery = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};

describe('FriendlyHeroSection stats', () => {
  beforeEach(() => {
    // Reduced motion → TickerNumber renders its final value synchronously,
    // so assertions don't depend on rAF plumbing.
    window.matchMedia = jest.fn(
      createMatchMedia((query) => query.includes('prefers-reduced-motion'))
    );
  });

  it('renders only the static fee block when there is no live data', async () => {
    renderHero([statsMock(null)]);
    await flushQuery();

    expect(screen.getByText('US$0.00')).toBeInTheDocument();
    expect(screen.getByText('network fees, always')).toBeInTheDocument();
    // No fallbacks: live blocks must not render without data.
    expect(screen.queryByText('deposited on-chain')).not.toBeInTheDocument();
    expect(screen.queryByText('raised in presale')).not.toBeInTheDocument();
  });

  it('renders deposited and presale blocks floored to whole dollars when live data exists', async () => {
    renderHero([
      statsMock({ depositedVolumeUsd: '125430.75', presaleRaisedUsd: '3597.21' }),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$125,430')).toBeInTheDocument();
    expect(screen.getByText('deposited on-chain')).toBeInTheDocument();
    expect(screen.getByText('US$3,597')).toBeInTheDocument();
    expect(screen.getByText('raised in presale')).toBeInTheDocument();
    // The fee block always accompanies live stats.
    expect(screen.getByText('US$0.00')).toBeInTheDocument();
  });

  it('renders a live block for each field independently', async () => {
    renderHero([
      statsMock({ depositedVolumeUsd: '52642.4', presaleRaisedUsd: null }),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$52,642')).toBeInTheDocument();
    expect(screen.queryByText('raised in presale')).not.toBeInTheDocument();
  });

  it('hides the whole stat row when a custom title is passed', async () => {
    renderHero(
      [statsMock({ depositedVolumeUsd: '125430.75', presaleRaisedUsd: '3597.21' })],
      { title: 'Custom page title' }
    );
    await flushQuery();

    expect(screen.getByText('Custom page title')).toBeInTheDocument();
    expect(screen.queryByText('US$0.00')).not.toBeInTheDocument();
    expect(screen.queryByText('deposited on-chain')).not.toBeInTheDocument();
  });
});
