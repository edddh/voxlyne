// Specchio JS di app/services/prompt_variables.py - stessa distinzione:
// {{system__xxx}} risolto dal provider voce (mai toccato qui),
// {{anything_else}} sostituito con projects.custom_variables. Usato per
// mostrare/testare l'anteprima sostituita (simulazione chat/vocale,
// editor prompt) senza aspettare una pubblicazione vera.
const TAG_PATTERN = /\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}/g

export function extractTags(text) {
  if (!text) return []
  const seen = []
  for (const match of text.matchAll(TAG_PATTERN)) {
    if (!seen.includes(match[1])) seen.push(match[1])
  }
  return seen
}

export function extractCustomTags(text) {
  return extractTags(text).filter((key) => !key.startsWith('system__'))
}

export function substituteCustomVariables(text, values) {
  if (!text) return text
  const v = values || {}
  return text.replace(TAG_PATTERN, (full, key) => {
    if (key.startsWith('system__')) return full
    if (v[key] != null && v[key] !== '') return String(v[key])
    return full
  })
}
