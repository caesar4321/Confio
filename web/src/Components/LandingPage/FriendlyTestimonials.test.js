import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyTestimonials from './FriendlyTestimonials';
import { LANDING_STATS } from './landingStats';
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
  result: { data: { landingStats } },
});

const flushQuery = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};

describe('FriendlyTestimonials stats', () => {
  it('renders only the static Free stat when there is no live data', async () => {
    renderTestimonials([statsMock(null)]);
    await flushQuery();

    expect(screen.getByText('Free')).toBeInTheDocument();
    expect(screen.getByText('For regular users')).toBeInTheDocument();
    // No fallbacks: entries without live data are filtered out entirely.
    expect(screen.queryByText('On-chain deposited volume')).not.toBeInTheDocument();
    expect(screen.queryByText('Raised in $CONFIO presale')).not.toBeInTheDocument();
  });

  it('renders live stats formatted via fmtUsd alongside the Free stat', async () => {
    renderTestimonials([
      statsMock({ depositedVolumeUsd: '125430.75', presaleRaisedUsd: '3597.21' }),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$125,430')).toBeInTheDocument();
    expect(screen.getByText('On-chain deposited volume')).toBeInTheDocument();
    expect(screen.getByText('US$3,597')).toBeInTheDocument();
    expect(screen.getByText('Raised in $CONFIO presale')).toBeInTheDocument();
    expect(screen.getByText('Free')).toBeInTheDocument();
  });

  it('keeps a partial live stat while filtering the missing one', async () => {
    renderTestimonials([
      statsMock({ depositedVolumeUsd: null, presaleRaisedUsd: '3597.21' }),
    ]);
    await flushQuery();

    expect(await screen.findByText('US$3,597')).toBeInTheDocument();
    expect(screen.queryByText('On-chain deposited volume')).not.toBeInTheDocument();
    expect(screen.getByText('Free')).toBeInTheDocument();
  });

  it('always renders the three anonymized testimonials', async () => {
    renderTestimonials([statsMock(null)]);
    await flushQuery();

    expect(screen.getAllByText('Anonymous user')).toHaveLength(3);
    expect(screen.getByText('🇻🇪 Venezuela')).toBeInTheDocument();
    expect(screen.getByText('🇦🇷 Argentina')).toBeInTheDocument();
    expect(screen.getByText('🇲🇽 México')).toBeInTheDocument();
  });
});
