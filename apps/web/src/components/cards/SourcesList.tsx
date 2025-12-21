import type { Citation } from '../../contracts'

export function SourcesList(props: { sources: Citation[] | undefined }) {
  const sources = props.sources ?? []
  if (sources.length === 0) return null

  return (
    <div className="mgSources">
      <div className="mgSourcesTitle">Sources</div>
      <ul className="mgSourcesList">
        {sources.map((s, idx) => (
          <li key={`${s.url}-${idx}`} className="mgSourcesItem">
            <a href={s.url} target="_blank" rel="noreferrer" className="mgLink">
              {s.title && s.title.trim().length > 0 ? s.title : s.url}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

