import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyHeroSection from './FriendlyHeroSection';
import { FUND_FLOW_STATS, LANDING_STATS } from './landingStats';
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

const flowMock = (totalUsd) => ({
  request: { query: FUND_FLOW_STATS },
  result: { data: { fundFlowStats: totalUsd == null ? null : { totalUsd, operationCount: 501 } } },
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

  it('renders no stat row when there is no live data', async () => {
    renderHero([statsMock(null), flowMock(null)]);
    await flushQuery();

    // No fallbacks: live blocks must not render without data.
    expect(screen.queryByText('registered users')).not.toBeInTheDocument();
    expect(screen.queryByText('moved in deposits and withdrawals')).not.toBeInTheDocument();
    expect(screen.queryByText('raised in presale')).not.toBeInTheDocument();
  });

  it('renders moved, presale, and registered-user blocks from live data', async () => {
    renderHero([
      statsMock({ presaleRaisedUsd: '3597.21', registeredUsers: 8164 }),
      flowMock(169651.26),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$169,651')).toBeInTheDocument();
    expect(screen.getByText('moved in deposits and withdrawals')).toBeInTheDocument();
    expect(screen.getByText('US$3,597')).toBeInTheDocument();
    expect(screen.getByText('raised in presale')).toBeInTheDocument();
    expect(screen.getByText('8,164')).toBeInTheDocument();
    expect(screen.getByText('registered users')).toBeInTheDocument();
    // The old deposits-only figure is gone.
    expect(screen.queryByText('deposited on-chain')).not.toBeInTheDocument();
  });

  it('renders a live block for each source independently', async () => {
    renderHero([statsMock(null), flowMock(52642.4)]);
    await flushQuery();

    expect(await screen.findByText('US$52,642')).toBeInTheDocument();
    expect(screen.queryByText('raised in presale')).not.toBeInTheDocument();
  });

  it('keeps presale and users when the moved stat is unavailable', async () => {
    renderHero([statsMock({ presaleRaisedUsd: '3597.21', registeredUsers: 8164 }), flowMock(null)]);
    await flushQuery();

    expect(await screen.findByText('US$3,597')).toBeInTheDocument();
    expect(screen.queryByText('moved in deposits and withdrawals')).not.toBeInTheDocument();
  });

  it('hides the whole stat row when a custom title is passed', async () => {
    renderHero(
      [statsMock({ presaleRaisedUsd: '3597.21', registeredUsers: 8164 }), flowMock(169651.26)],
      { title: 'Custom page title' }
    );
    await flushQuery();

    expect(screen.getByText('Custom page title')).toBeInTheDocument();
    expect(screen.queryByText('registered users')).not.toBeInTheDocument();
    expect(screen.queryByText('moved in deposits and withdrawals')).not.toBeInTheDocument();
  });
});
