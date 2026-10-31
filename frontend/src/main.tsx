import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '@/app/App'
import { uk } from '@/i18n/uk'
import './index.css'

const rootElement = document.getElementById('root')
if (!rootElement) throw new Error('Root element #root not found')

document.title = uk.app.name

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
