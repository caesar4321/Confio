import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyTestimonials from './FriendlyTestimonials';
import { FUND_FLOW_STATS, LANDING_STATS } from './landingStats';
import { LanguageProvider } from '../../contexts/LanguageContext';

// jsdom's navigator.language is en-US → English copy.
const renderTestimonials = (mocks) =>
  render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <LanguageProvider>
        <FriendlyTestimonials />
      </LanguageProvider>
    </MockedProvider>
  );

const statsMock = (landingStats) => ({
  request: { query: LANDING_STATS },
  result: {
    data: {
      landingStats: landingStats
        ? { registeredUsers: null, ...landingStats }
        : null,
    },
  },
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

describe('FriendlyTestimonials stats', () => {
  it('renders only the static transfer-fee stat when there is no live data', async () => {
    renderTestimonials([statsMock(null), flowMock(null)]);
    await flushQuery();

    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.getByText('Transfers between users')).toBeInTheDocument();
    // No fallbacks: entries without live data are filtered out entirely.
    expect(screen.queryByText('Moved in deposits and withdrawals')).not.toBeInTheDocument();
    expect(screen.queryByText('Raised in $CONFIO presale')).not.toBeInTheDocument();
  });

  it('renders live stats formatted via fmtUsd alongside the transfer-fee stat', async () => {
    renderTestimonials([
      statsMock({ presaleRaisedUsd: '3597.21' }),
      flowMock(169651.26),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$169,651')).toBeInTheDocument();
    expect(screen.getByText('Moved in deposits and withdrawals')).toBeInTheDocument();
    expect(screen.queryByText('On-chain deposited volume')).not.toBeInTheDocument();
    expect(screen.getByText('US$3,597')).toBeInTheDocument();
    expect(screen.getByText('Raised in $CONFIO presale')).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('keeps a partial live stat while filtering the missing one', async () => {
    renderTestimonials([
      statsMock({ presaleRaisedUsd: '3597.21' }),
      flowMock(null),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$3,597')).toBeInTheDocument();
    expect(screen.queryByText('Moved in deposits and withdrawals')).not.toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('always renders the three anonymized testimonials', async () => {
    renderTestimonials([statsMock(null), flowMock(null)]);
    await flushQuery();

    expect(screen.getAllByText('Anonymous user')).toHaveLength(3);
    expect(screen.getByText('🇻🇪 Venezuela')).toBeInTheDocument();
    expect(screen.getByText('🇦🇷 Argentina')).toBeInTheDocument();
    expect(screen.getByText('🇲🇽 México')).toBeInTheDocument();
  });
});
