import { useMemo } from 'react'
import { Rnd } from 'react-rnd'
import type { BoardState, Card, Rect } from '../contracts'
import { ChartCardView } from './cards/ChartCardView'
import { ListCardView } from './cards/ListCardView'
import { recordCardDismissed, recordCardRectChanged } from '../telemetry/sessionTelemetry'

const DEFAULT_RECT: Omit<Rect, 'x' | 'y'> = { w: 420, h: 280 }

function autoPlaceRect(index: number): Rect {
  const gutter = 16
  const colWidth = DEFAULT_RECT.w + gutter
  const rowHeight = DEFAULT_RECT.h + gutter
  const col = index % 2
  const row = Math.floor(index / 2)
  return {
    x: gutter + col * colWidth,
    y: gutter + row * rowHeight,
    w: DEFAULT_RECT.w,
    h: DEFAULT_RECT.h,
  }
}

function cardTitle(card: Card): string {
  return card.props.title
}

export function Whiteboard(props: {
  boardState: BoardState
  dismissed: Set<string>
  sendClientBoardAction: (action: unknown) => void
  onDismiss: (cardId: string) => void
}) {
  const cards = useMemo(() => Object.values(props.boardState.cards ?? {}), [props.boardState.cards])
  const visibleCards = useMemo(
    () => cards.filter((c) => !props.dismissed.has(c.card_id)),
    [cards, props.dismissed],
  )

  return (
    <div className="mgWhiteboard">
      <div className="mgPanelTitle">Whiteboard</div>

      <div className="mgCanvas">
        {visibleCards.length === 0 ? (
          <div className="mgMuted mgEmptyState">
            No cards yet. Send transcript events to generate board state.
          </div>
        ) : null}

        {visibleCards.map((card, idx) => {
          const serverRect = props.boardState.layout?.[card.card_id]
          const rect = serverRect ?? autoPlaceRect(idx)

          return (
            <Rnd
              key={card.card_id}
              bounds="parent"
              dragHandleClassName="mgCardHeader"
              size={{ width: rect.w, height: rect.h }}
              position={{ x: rect.x, y: rect.y }}
              minWidth={260}
              minHeight={180}
              onDragStop={(_, data) => {
                const newRect = { ...rect, x: data.x, y: data.y }
                recordCardRectChanged({
                  interaction: 'drag',
                  cardId: card.card_id,
                  rect: newRect,
                })
                props.sendClientBoardAction({
                  type: 'move_card',
                  card_id: card.card_id,
                  rect: newRect,
                })
              }}
              onResizeStop={(_, __, ref, ___, position) => {
                const width = ref.offsetWidth
                const height = ref.offsetHeight
                const newRect = { x: position.x, y: position.y, w: width, h: height }
                recordCardRectChanged({
                  interaction: 'resize',
                  cardId: card.card_id,
                  rect: newRect,
                })
                props.sendClientBoardAction({
                  type: 'move_card',
                  card_id: card.card_id,
                  rect: newRect,
                })
              }}
            >
              <div className="mgCard">
                <div className="mgCardHeader">
                  <div className="mgCardTitle">{cardTitle(card)}</div>
                  <button
                    className="mgIconButton"
                    title="Dismiss card"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      recordCardDismissed(card.card_id)
                      props.sendClientBoardAction({
                        type: 'dismiss_card',
                        card_id: card.card_id,
                        reason: 'user dismissed',
                      })
                      props.onDismiss(card.card_id)
                    }}
                  >
                    Dismiss
                  </button>
                </div>
                {card.kind === 'chart' ? <ChartCardView card={card} /> : null}
                {card.kind === 'list' ? <ListCardView card={card} /> : null}
              </div>
            </Rnd>
          )
        })}
      </div>
    </div>
  )
}
