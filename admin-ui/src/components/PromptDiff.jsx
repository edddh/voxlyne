import { diffWords } from 'diff'

/**
 * Evidenzia le differenze tra il testo pubblicato (quello che sente
 * davvero chi chiama) e la bozza corrente (incluse le modifiche non
 * ancora salvate) - maintainer, 19/08: "sarebbe bello che fosse evidenziata
 * la differenza tra bozza e pubblicato nel testo".
 */
// Normalizza gli "a capo" prima di confrontare: un <textarea> puo'
// restituire \r\n mentre il testo salvato/pubblicato arriva dall'API con
// \n soltanto - senza questo, OGNI riga risulterebbe diversa (non solo
// quella davvero modificata), perche' diffWords tratta \r\n e \n come
// token distinti. Trovato in ambiente di sviluppo (19/08): maintainer aveva aggiunto
// una sola riga ma il diff segnava tutto il testo come cambiato.
export const normalizeNewlines = (text) => (text || '').replace(/\r\n/g, '\n')

function PromptDiff({ published, draft }) {
  const normalizedPublished = normalizeNewlines(published)
  const normalizedDraft = normalizeNewlines(draft)
  if (normalizedPublished === normalizedDraft) return null

  const parts = diffWords(normalizedPublished, normalizedDraft)

  return (
    <pre
      style={{
        fontFamily: 'monospace',
        fontSize: 12,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        background: '#1e1e1e',
        color: '#d4d4d4',
        padding: 12,
        borderRadius: 8,
        maxHeight: 260,
        overflow: 'auto',
        margin: 0,
      }}
    >
      {parts.map((part, i) => {
        if (part.added) {
          return (
            <span key={i} style={{ background: 'rgba(82, 196, 26, 0.25)', color: '#95de64' }}>
              {part.value}
            </span>
          )
        }
        if (part.removed) {
          return (
            <span key={i} style={{ background: 'rgba(255, 77, 79, 0.2)', color: '#ff7875', textDecoration: 'line-through' }}>
              {part.value}
            </span>
          )
        }
        return <span key={i}>{part.value}</span>
      })}
    </pre>
  )
}

export default PromptDiff
