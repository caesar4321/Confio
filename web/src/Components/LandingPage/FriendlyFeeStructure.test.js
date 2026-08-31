import React from 'react';
import { render, screen } from '@testing-library/react';
import FriendlyFeeStructure from './FriendlyFeeStructure';
import { LanguageProvider } from '../../contexts/LanguageContext';

describe('FriendlyFeeStructure', () => {
  it('presents one conversion rule instead of personal and business plans', () => {
    render(
      <LanguageProvider>
        <FriendlyFeeStructure />
      </LanguageProvider>
    );

    expect(screen.getByText('The same conversion fee for people and businesses')).toBeInTheDocument();
    expect(screen.getAllByText('0.9%')).toHaveLength(2);
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.getAllByText('Confío fee US$0.90')).toHaveLength(2);
    expect(screen.getByText(/Send and receive between users/)).toBeInTheDocument();
    expect(screen.getByText(/Confío Pay payments carry a 0.9% fee/)).toBeInTheDocument();
    expect(screen.getByText(/any third-party provider charge/)).toBeInTheDocument();
    expect(screen.queryByText('Personal User')).not.toBeInTheDocument();
    expect(screen.queryByText('FREE')).not.toBeInTheDocument();
  });
});
