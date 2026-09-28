import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'
import './planner.css'
import 'maplibre-gl/dist/maplibre-gl.css'
import './dark.css'
import './dark-extra.css'

// Dark is the default; the header toggle stores the choice.
document.documentElement.dataset.theme = localStorage.getItem('pond-theme') === 'light' ? 'light' : 'dark'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
