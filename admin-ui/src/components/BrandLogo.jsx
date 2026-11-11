import logo from '../assets/voxlyne-logo.svg'

export function BrandLogo({ alt = 'Voxlyne', className, style }) {
  return <img src={logo} alt={alt} className={className} style={style} />
}

export function applyBrandMetadata() {
  if (typeof document !== 'undefined') document.title = 'Voxlyne'
}
