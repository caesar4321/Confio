import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyHeroSection from './FriendlyHeroSection';
import { FUND_FLOW_STATS, INVEST_TRADED_USD, LANDING_STATS, RESERVE_STATS } from './landingStats';
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

const reserveMock = (statsSummary) => ({
  request: { query: RESERVE_STATS },
  result: { data: { statsSummary } },
});

const investMock = (investTradedUsd) => ({
  request: { query: INVEST_TRADED_USD },
  result: { data: { investTradedUsd } },
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

  it('renders reserves and traded volume, the app Home tiles', async () => {
    renderHero([
      statsMock(null),
      flowMock(null),
      reserveMock({ totalValueLocked: 5830.9, protectedSavings: 5830.9, cusdBscReserve: 256.01, usdyReserve: 2170.59, statsSource: 'algorand' }),
      investMock(4690.4),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$8,257')).toBeInTheDocument();
    expect(screen.getByText('in reserves backing Confío dollars')).toBeInTheDocument();
    expect(screen.getByText('US$4,690')).toBeInTheDocument();
    expect(screen.getByText('traded in stocks, gold, bitcoin and futures')).toBeInTheDocument();
  });

  it('never shows a partial reserve total or a private traded figure', async () => {
    renderHero([
      statsMock(null),
      flowMock(null),
      reserveMock({ totalValueLocked: 5830.9, protectedSavings: 5830.9, cusdBscReserve: null, usdyReserve: 2170.59, statsSource: 'algorand' }),
      investMock(null),
    ]);
    await flushQuery();

    expect(screen.queryByText('in reserves backing Confío dollars')).not.toBeInTheDocument();
    expect(screen.queryByText('traded in stocks, gold, bitcoin and futures')).not.toBeInTheDocument();
  });

  it('hides reserves while the legacy figure is a database estimate', async () => {
    renderHero([
      statsMock(null),
      flowMock(null),
      reserveMock({ totalValueLocked: 0, protectedSavings: 0, cusdBscReserve: 256.01, usdyReserve: 2170.59, statsSource: 'database_fallback' }),
      investMock(null),
    ]);
    await flushQuery();

    expect(screen.queryByText('in reserves backing Confío dollars')).not.toBeInTheDocument();
    expect(screen.queryByText('US$2,426')).not.toBeInTheDocument();
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
