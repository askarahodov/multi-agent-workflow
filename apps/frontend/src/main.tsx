import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

// Minimal entry point. The canvas editor, palette and property panels are
// introduced by downstream tasks (T2/T3). This shell keeps `vite build` green.

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
