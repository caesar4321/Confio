import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import FriendlyFeeStructure from './FriendlyFeeStructure';
import { PUBLIC_FEES, fmtBpsPct } from './landingStats';
import { LanguageProvider } from '../../contexts/LanguageContext';

// jsdom's navigator.language is en-US → English copy.
const renderFees = (publicFees) =>
  render(
    <MockedProvider
      mocks={[{ request: { query: PUBLIC_FEES }, result: { data: { publicFees } } }]}
      addTypename={false}
    >
      <LanguageProvider>
        <FriendlyFeeStructure />
      </LanguageProvider>
    </MockedProvider>
  );

const flushQuery = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

describe('FriendlyFeeStructure', () => {
  it('presents one conversion rule with the server-quoted fees', async () => {
    renderFees({ conversionFeeBps: 90, payFeeBps: 90 });
    await flushQuery();

    expect(screen.getByText('The same conversion fee for people and businesses')).toBeInTheDocument();
    expect(screen.getAllByText('0.9%')).toHaveLength(2);
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.getAllByText('Confío fee US$0.90')).toHaveLength(2);
    expect(screen.getAllByText('You receive US$99.10')).toHaveLength(2);
    expect(screen.getByText(/Send and receive between users/)).toBeInTheDocument();
    expect(screen.getByText(/Confío Pay payments carry a 0.9% fee/)).toBeInTheDocument();
    expect(screen.getByText(/any third-party provider charge/)).toBeInTheDocument();
    expect(screen.queryByText('Personal User')).not.toBeInTheDocument();
  });

  it('follows a changed fee instead of a hardcoded one', async () => {
    renderFees({ conversionFeeBps: 50, payFeeBps: 90 });
    await flushQuery();

    expect(screen.getAllByText('0.5%')).toHaveLength(2);
    expect(screen.getAllByText('Confío fee US$0.50')).toHaveLength(2);
    expect(screen.queryByText('0.9%')).not.toBeInTheDocument();
  });

  it('shows no fee figures without live data', async () => {
    renderFees(null);
    await flushQuery();

    expect(screen.queryByText(/0\.9%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/US\$0\.90/)).not.toBeInTheDocument();
    expect(screen.getByText(/carry their own fee/)).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
  });
});

describe('fmtBpsPct', () => {
  it('formats basis points per locale', () => {
    expect(fmtBpsPct(90, ',')).toBe('0,9%');
    expect(fmtBpsPct(75, '.')).toBe('0.75%');
    expect(fmtBpsPct(100, ',')).toBe('1%');
    expect(fmtBpsPct(0, ',')).toBe('0%');
  });
});
