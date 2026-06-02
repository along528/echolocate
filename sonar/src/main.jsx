import React from 'react';
import { createRoot } from 'react-dom/client';
import Sonar from './Sonar.jsx';

import './style.css';
import './sonar.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Sonar initialView="map" />
  </React.StrictMode>,
);
