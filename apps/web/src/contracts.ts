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

export type MindmapPoint = {
  x: number
  y: number
}

export type MindmapNode = {
  node_id: string
  parent_id: string | null
  text: string
  collapsed: boolean
  sources: Citation[]
}

export type MindmapState = {
  root_id: string
  nodes: Record<string, MindmapNode>
  layout: Record<string, MindmapPoint>
}

export type MindmapAction =
  | { type: 'upsert_node'; node: MindmapNode }
  | { type: 'set_node_pos'; node_id: string; pos: MindmapPoint }
  | { type: 'set_collapsed'; node_id: string; collapsed: boolean }
  | { type: 'rename_node'; node_id: string; text: string }
  | { type: 'reparent_node'; node_id: string; new_parent_id: string | null }
  | { type: 'delete_subtree'; node_id: string }

export type OutgoingMessage =
  | { type: 'transcript_event'; event: TranscriptEvent }
  | {
      type: 'set_session_context'
      default_location: string
      no_browse?: boolean
      years?: number
      month?: number
      mindmap_ai?: boolean
    }
  | { type: 'export_board' }
  | {
      type: 'import_board'
      state: BoardState
      default_location?: string | null
      no_browse?: boolean | null
    }
  | { type: 'client_board_action'; action: unknown }
  | { type: 'client_mindmap_action'; action: MindmapAction }
  | { type: 'run_ai' }
  | { type: 'reset' }

export type IncomingBoardActionsMessage = {
  type: 'board_actions'
  actions: unknown[]
  state: BoardState
}

export type IncomingBoardExportMessage = {
  type: 'board_export'
  state: BoardState
  default_location?: string
  no_browse?: boolean
}

export type IncomingMindmapActionsMessage = {
  type: 'mindmap_actions'
  actions: MindmapAction[]
  state: MindmapState
}

export type MindmapStatus = 'idle' | 'running'

export type IncomingMindmapStatusMessage = {
  type: 'mindmap_status'
  status: MindmapStatus
}

export type IncomingStatusMessage = { type: 'status'; message: string }

export type IncomingErrorMessage = { type: 'error'; message: string; details?: unknown }

export type IncomingMessage =
  | IncomingBoardActionsMessage
  | IncomingBoardExportMessage
  | IncomingMindmapActionsMessage
  | IncomingMindmapStatusMessage
  | IncomingStatusMessage
  | IncomingErrorMessage

export const emptyBoardState = (): BoardState => ({
  cards: {},
  layout: {},
  dismissed: {},
})

export const emptyMindmapState = (): MindmapState => ({
  root_id: 'mm:root',
  nodes: {},
  layout: {},
})
