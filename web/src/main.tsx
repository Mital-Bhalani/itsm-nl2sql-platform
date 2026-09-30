import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, load } from './lib/settings.tsx'

// Set light/dark on <html> before the first paint so a dark user never sees a light flash.
applyTheme(load().theme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
