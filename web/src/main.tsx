import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource/host-grotesk/400.css'
import '@fontsource/host-grotesk/500.css'
import App from './App'
import './app.css'

class Boundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <main className="container"><h1>页面暂时无法显示</h1><p>请刷新页面。如果仍有问题，请检查 Horizon Web 服务日志。</p><button type="button" onClick={() => window.location.reload()}>刷新页面</button></main> : this.props.children }
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><Boundary><App /></Boundary></React.StrictMode>)
