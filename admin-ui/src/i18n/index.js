import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import it from './locales/it.json'
import en from './locales/en.json'

// Italiano resta la lingua sorgente/di riferimento (l'app è nata in
// italiano) - l'inglese è la lingua aggiunta ora
// (maintainer, 16/09: "internazionalizzare l'interfaccia... in inglese").
// Nuove lingue future si aggiungono solo qui + un nuovo
// locales/<lang>.json, nessun'altra modifica di codice necessaria.
export const SUPPORTED_LANGUAGES = [
  { code: 'it', label: 'Italiano' },
  { code: 'en', label: 'English' },
]

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      it: { translation: it },
      en: { translation: en },
    },
    fallbackLng: 'it',
    supportedLngs: ['it', 'en'],
    interpolation: {
      escapeValue: false, // React già esegue l'escape
    },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'ascolta_language',
    },
  })

export default i18n
