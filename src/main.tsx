import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/vazirmatn/arabic-400.css';
import '@fontsource/vazirmatn/arabic-700.css';
import '@fontsource/vazirmatn/latin-400.css';
import '@fontsource/vazirmatn/latin-700.css';
import './styles/app.css';
import './styles/mobile-controls.css';
import { App } from './App';

// Polyfill CanvasRenderingContext2D.roundRect for older Android/iOS WebViews
if (
  typeof CanvasRenderingContext2D !== 'undefined' &&
  !CanvasRenderingContext2D.prototype.roundRect
) {
  CanvasRenderingContext2D.prototype.roundRect = function (
    x: number,
    y: number,
    w: number,
    h: number,
    radii?: number | DOMPointInit | Array<number | DOMPointInit>
  ) {
    const r =
      typeof radii === 'number'
        ? Math.min(radii, w / 2, h / 2)
        : Array.isArray(radii) && typeof radii[0] === 'number'
        ? Math.min(radii[0], w / 2, h / 2)
        : 6;
    this.moveTo(x + r, y);
    this.arcTo(x + w, y, x + w, y + h, r);
    this.arcTo(x + w, y + h, x, y + h, r);
    this.arcTo(x, y + h, x, y, r);
    this.arcTo(x, y, x + w, y, r);
    this.closePath();
    return this;
  };
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
