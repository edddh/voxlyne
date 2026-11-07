import logo from '../assets/ascolta-logo.svg'

export function BrandLogo({ alt = 'Ascolta', className, style }) {
  return <img src={logo} alt={alt} className={className} style={style} />
}

export function applyBrandMetadata() {
  if (typeof document !== 'undefined') document.title = 'Ascolta'
}
