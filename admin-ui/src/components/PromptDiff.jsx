import { diffWords } from 'diff'

/**
 * Evidenzia le differenze tra il testo pubblicato (quello che sente
 * davvero chi chiama) e la bozza corrente (incluse le modifiche non
 * ancora salvate) - maintainer, 19/08: "sarebbe bello che fosse evidenziata
 * la differenza tra bozza e pubblicato nel testo".
 */
function PromptDiff({ published, draft }) {
  if (published === draft) return null

  const parts = diffWords(published || '', draft || '')

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
