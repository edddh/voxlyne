import { useTranslation } from 'react-i18next'
import itIT from 'antd/locale/it_IT'
import enUS from 'antd/locale/en_US'

// antd ha i suoi testi propri (paginazione, date picker, conferme...) -
// separati dalle nostre traduzioni in locales/*.json - e vanno tenuti in
// sincrono con la lingua scelta dall'utente (react-i18next), altrimenti
// il resto dell'interfaccia cambia lingua ma i componenti antd restano
// fermi in italiano.
const ANTD_LOCALES = {
  it: itIT,
  en: enUS,
}

export function RootWithLocale({ children }) {
  const { i18n } = useTranslation()
  const antdLocale = ANTD_LOCALES[i18n.language] || ANTD_LOCALES[i18n.language?.split('-')[0]] || itIT
  return children(antdLocale)
}
