import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';
// Design tokens + global baseline (ADR-110 §3.1) are loaded once here.
import './styles/tokens.css';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
