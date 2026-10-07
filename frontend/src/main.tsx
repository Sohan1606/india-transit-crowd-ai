import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('India Transit Crowd AI frontend crashed during render.', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <main style={{ minHeight: '100vh', padding: '48px', background: '#10120f', color: '#e8e8df', fontFamily: 'Arial, sans-serif' }}>
          <p style={{ color: '#c7ee7b', letterSpacing: '.12em', fontWeight: 700 }}>FRONTEND RUNTIME ERROR</p>
          <h1 style={{ marginTop: '16px', fontSize: '42px' }}>The interface could not render.</h1>
          <p style={{ maxWidth: '760px', marginTop: '18px', lineHeight: 1.6, color: '#858980' }}>{this.state.error.message}</p>
          <button type="button" onClick={() => window.location.reload()} style={{ marginTop: '24px', padding: '10px 14px', border: '1px solid #c7ee7b', background: 'transparent', color: '#c7ee7b', cursor: 'pointer' }}>
            Reload interface
          </button>
        </main>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><AppErrorBoundary><App /></AppErrorBoundary></React.StrictMode>,
)
