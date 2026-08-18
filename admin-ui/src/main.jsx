import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme as antdTheme } from 'antd'
import itIT from 'antd/locale/it_IT'
import App from './App'
import { AuthProvider } from './hooks/useAuth'
import './index.css'

// Palette di brand Ascolta: bianco e arancione su sfondo scuro.
// Valori esatti prelevati dal logo (Ascolta.png) — non arrotondati a occhio.
export const BRAND = {
  bg: '#121417', // quasi nero: usato per la maggior parte dello schermo (sider, layout)
  bgElevated: '#1E2227', // grigio molto scuro: solo per header/dropdown/modali
  bgContainer: '#191C20', // grigio molto scuro, appena sopra il nero: card/contenuto
  border: '#2A2E34',
  orange: '#F47A1F',
  orangeSoft: 'rgba(244, 122, 31, 0.16)',
  white: '#FFFFFF',
  textDim: 'rgba(255, 255, 255, 0.65)',
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider
      locale={itIT}
      theme={{
        algorithm: antdTheme.darkAlgorithm,
        token: {
          colorPrimary: BRAND.orange,
          colorBgBase: BRAND.bg,
          colorBgLayout: BRAND.bg,
          colorBgContainer: BRAND.bgContainer,
          colorBgElevated: BRAND.bgElevated,
          colorBorder: BRAND.border,
          colorBorderSecondary: BRAND.border,
          colorText: BRAND.white,
          colorTextSecondary: BRAND.textDim,
          colorLink: BRAND.orange,
          colorLinkHover: '#FF9A3D',
          borderRadius: 8,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        },
        components: {
          Layout: {
            headerBg: BRAND.bgElevated,
            siderBg: BRAND.bg,
            bodyBg: BRAND.bg,
          },
          Menu: {
            darkItemBg: BRAND.bg,
            darkItemSelectedBg: BRAND.orangeSoft,
            darkItemSelectedColor: BRAND.orange,
            darkItemHoverBg: 'rgba(255,255,255,0.04)',
          },
          Button: {
            primaryShadow: 'none',
          },
        },
      }}
    >
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
)
