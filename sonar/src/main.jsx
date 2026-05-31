import React from 'react';
import { createRoot } from 'react-dom/client';
import LayoutD from './LayoutD.jsx';

// Prototype styles, ported verbatim (consolidation tracked in TODO.md).
import './style.css';
import './styles/layout-a.css';
import './styles/layout-c.css';
import './styles/layout-d.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <LayoutD initialView="map" />
  </React.StrictMode>,
);
