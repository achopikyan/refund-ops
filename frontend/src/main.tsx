import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Workspace from './Workspace';
import './styles.css';
const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
createRoot(document.getElementById('root')!).render(<React.StrictMode>
  <QueryClientProvider client={client}><Workspace /></QueryClientProvider>
</React.StrictMode>);
