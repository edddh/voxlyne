import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme as antdTheme } from 'antd'
import App from './App'
import { AuthProvider } from './hooks/useAuth'
import './index.css'
import './i18n'
import { applyBrandMetadata } from './components/BrandLogo'
import { RootWithLocale } from './i18n/RootWithLocale'

// Palette Ascolta: petrolio, acqua e verde salvia. Non deriva dal brand legacy.
export const BRAND = {
  bg: '#0E2025',
  bgElevated: '#153A4A',
  bgContainer: '#112C34',
  border: '#244B51',
  orange: '#00A8A8',
  orangeSoft: 'rgba(0, 168, 168, 0.15)',
  white: '#F4FAF8',
  textDim: 'rgba(244, 250, 248, 0.68)',
}

applyBrandMetadata()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RootWithLocale>
      {(antdLocale) => (
        <ConfigProvider
          locale={antdLocale}
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
              colorLinkHover: '#00A8A8',
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
                darkItemHoverBg: 'rgba(0,109,119,0.06)',
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
      )}
    </RootWithLocale>
  </React.StrictMode>
)
