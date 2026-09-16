import logo from '../assets/ascolta-logo.png'
import demoLogo from '../assets/ascolta-logo-demo.png'

const isDemoHost = typeof window !== 'undefined' && window.location.hostname === 'call.demo.ai'

export function BrandLogo({ alt = 'Ascolta', className, style }) {
  if (!isDemoHost) {
    return <img src={logo} alt={alt} className={className} style={style} />
  }

  // On the Demo hostname keep the Ascolta mark but clip the partner suffix.
  return (
    <img src={demoLogo} alt={alt} className={className} style={style} />
  )
}

export function applyBrandMetadata() {
  if (typeof document !== 'undefined') document.title = 'Ascolta'
}
