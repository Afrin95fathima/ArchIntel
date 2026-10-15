import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { AccessShell } from './security/AccessShell';
import './design-tokens.css';
import './screens.css';
import './ui/components.css';

const client = new QueryClient();
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={client}><AccessShell><App /></AccessShell></QueryClientProvider></React.StrictMode>,
);
