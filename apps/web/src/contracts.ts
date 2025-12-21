export type TranscriptEvent = {
  timestamp: string
  speaker: string | null
  text: string
  confidence?: number | null
  is_final: boolean
}

export type Citation = {
  url: string
  title?: string | null
  retrieved_at?: string
  published_at?: string | null
}

export type CardKind = 'chart' | 'list'

export type Rect = {
  x: number
  y: number
  w: number
  h: number
}

export type ChartSeriesPoint = {
  label: string
  value: number
}

export type ChartCard = {
  card_id: string
  kind: 'chart'
  props: {
    title: string
    subtitle?: string | null
    x_label?: string
    y_label?: string
    points: ChartSeriesPoint[]
  }
  sources: Citation[]
}

export type ListItem = {
  text: string
  url?: string | null
  meta?: string | null
}

export type ListCard = {
  card_id: string
  kind: 'list'
  props: {
    title: string
    items: ListItem[]
  }
  sources: Citation[]
}

export type Card = ChartCard | ListCard

export type BoardState = {
  cards: Record<string, Card>
  layout: Record<string, Rect>
  dismissed: Record<string, string>
}

export type OutgoingMessage =
  | { type: 'transcript_event'; event: TranscriptEvent }
  | { type: 'reset' }

export type IncomingBoardActionsMessage = {
  type: 'board_actions'
  actions: unknown[]
  state: BoardState
}

export type IncomingStatusMessage = { type: 'status'; message: string }

export type IncomingMessage = IncomingBoardActionsMessage | IncomingStatusMessage

export const emptyBoardState = (): BoardState => ({
  cards: {},
  layout: {},
  dismissed: {},
})

