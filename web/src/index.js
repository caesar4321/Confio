import React from 'react';
import { createRoot } from 'react-dom/client';
import FriendlyApp from './FriendlyApp';

const container = document.getElementById('root');
const root = createRoot(container);

// Always render the Friendly version
root.render(<FriendlyApp />);
