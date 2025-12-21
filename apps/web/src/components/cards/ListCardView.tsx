import type { ListCard } from '../../contracts'
import { SourcesList } from './SourcesList'

export function ListCardView(props: { card: ListCard }) {
  const { card } = props
  return (
    <div className="mgCardBody">
      <ul className="mgList">
        {card.props.items.map((item, idx) => (
          <li key={`${item.text}-${idx}`} className="mgListItem">
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer" className="mgLink">
                {item.text}
              </a>
            ) : (
              <span>{item.text}</span>
            )}
            {item.meta ? <div className="mgMuted mgListMeta">{item.meta}</div> : null}
          </li>
        ))}
      </ul>
      <SourcesList sources={card.sources} />
    </div>
  )
}

