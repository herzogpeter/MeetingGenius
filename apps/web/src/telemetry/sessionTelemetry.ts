import type {
  Card,
  CardKind,
  IncomingBoardActionsMessage,
  IncomingErrorMessage,
  Rect,
  TranscriptEvent,
} from '../contracts'

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'

type SessionTelemetryEvent =
  | {
      type: 'session_started'
      ts: string
      session_id: string
    }
  | {
      type: 'connection_state_changed'
      ts: string
      state: ConnectionState
    }
  | {
      type: 'transcript_event_sent'
      ts: string
      event: TranscriptEvent
    }
  | {
      type: 'board_actions_received'
      ts: string
      actions_count: number
      cards_count: number
      card_kinds: Record<CardKind, number>
    }
  | {
      type: 'server_error_received'
      ts: string
      message: string
      details?: unknown
    }
  | {
      type: 'card_dismissed'
      ts: string
      card_id: string
    }
  | {
      type: 'card_rect_changed'
      ts: string
      interaction: 'drag' | 'resize'
      card_id: string
      rect: Rect
    }
  | {
      type: 'assumptions_changed'
      ts: string
      changes: {
        location?: { prev: string; next: string }
        years?: { prev: number; next: number }
        no_browse?: { prev: boolean; next: boolean }
        mindmap_ai?: { prev: boolean; next: boolean }
      }
      current: { location: string; years: number; no_browse: boolean; mindmap_ai: boolean }
    }
  | {
      type: 'refresh_last_request_clicked'
      ts: string
      location: string
      years: number
      last_event?: { timestamp: string; speaker: string | null; text_preview: string }
    }
  | {
      type: 'run_ai_clicked'
      ts: string
    }
  | {
      type: 'board_export_requested'
      ts: string
    }
  | {
      type: 'board_export_downloaded'
      ts: string
      filename: string
    }
  | {
      type: 'board_import_sent'
      ts: string
      filename?: string
    }
  | {
      type: 'board_import_error'
      ts: string
      stage: 'parse' | 'send' | 'server'
      message: string
      filename?: string
    }

export type SessionTelemetryExport = {
  session_id: string
  started_at: string
  page_url?: string
  user_agent?: string
  events: SessionTelemetryEvent[]
}

const MAX_EVENTS = 5000

function nowIso(): string {
  return new Date().toISOString()
}

function randomId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function safePageUrl(): string | undefined {
  try {
    return typeof window !== 'undefined' ? window.location?.href : undefined
  } catch {
    return undefined
  }
}

function safeUserAgent(): string | undefined {
  try {
    return typeof navigator !== 'undefined' ? navigator.userAgent : undefined
  } catch {
    return undefined
  }
}

function summarizeCardKinds(cards: Record<string, Card> | undefined): Record<CardKind, number> {
  const counts: Record<CardKind, number> = { chart: 0, list: 0 }
  if (!cards) return counts
  for (const card of Object.values(cards)) counts[card.kind] += 1
  return counts
}

function createNewSession(): SessionTelemetryExport {
  const startedAt = nowIso()
  const sessionId = randomId()
  return {
    session_id: sessionId,
    started_at: startedAt,
    page_url: safePageUrl(),
    user_agent: safeUserAgent(),
    events: [{ type: 'session_started', ts: startedAt, session_id: sessionId }],
  }
}

let currentSession: SessionTelemetryExport = createNewSession()

function pushEvent(event: SessionTelemetryEvent): void {
  currentSession.events.push(event)
  if (currentSession.events.length > MAX_EVENTS) {
    currentSession.events.splice(0, currentSession.events.length - MAX_EVENTS)
  }
}

export function clearSessionTelemetry(): void {
  currentSession = createNewSession()
}

export function getSessionTelemetryExport(): SessionTelemetryExport {
  return JSON.parse(JSON.stringify(currentSession)) as SessionTelemetryExport
}

export function downloadSessionTelemetryJson(): void {
  const snapshot = getSessionTelemetryExport()
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
  const ts = nowIso().replace(/[:.]/g, '-')
  const filename = `meetinggenius-session-${snapshot.session_id}-${ts}.json`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function recordConnectionStateChanged(state: ConnectionState): void {
  pushEvent({ type: 'connection_state_changed', ts: nowIso(), state })
}

export function recordTranscriptEventSent(event: TranscriptEvent): void {
  pushEvent({ type: 'transcript_event_sent', ts: nowIso(), event })
}

export function recordBoardActionsReceived(message: IncomingBoardActionsMessage): void {
  pushEvent({
    type: 'board_actions_received',
    ts: nowIso(),
    actions_count: Array.isArray(message.actions) ? message.actions.length : 0,
    cards_count: message.state?.cards ? Object.keys(message.state.cards).length : 0,
    card_kinds: summarizeCardKinds(message.state?.cards),
  })
}

export function recordServerErrorReceived(message: IncomingErrorMessage): void {
  pushEvent({
    type: 'server_error_received',
    ts: nowIso(),
    message: message.message,
    details: message.details,
  })
}

export function recordCardDismissed(cardId: string): void {
  pushEvent({ type: 'card_dismissed', ts: nowIso(), card_id: cardId })
}

export function recordCardRectChanged(args: {
  interaction: 'drag' | 'resize'
  cardId: string
  rect: Rect
}): void {
  pushEvent({
    type: 'card_rect_changed',
    ts: nowIso(),
    interaction: args.interaction,
    card_id: args.cardId,
    rect: args.rect,
  })
}

export function recordAssumptionsChanged(args: {
  changes: {
    location?: { prev: string; next: string }
    years?: { prev: number; next: number }
    no_browse?: { prev: boolean; next: boolean }
    mindmap_ai?: { prev: boolean; next: boolean }
  }
  current: { location: string; years: number; no_browse: boolean; mindmap_ai: boolean }
}): void {
  pushEvent({ type: 'assumptions_changed', ts: nowIso(), changes: args.changes, current: args.current })
}

export function recordRefreshLastRequestClicked(args: {
  location: string
  years: number
  lastEvent: TranscriptEvent | null
}): void {
  const textPreview = args.lastEvent?.text ? args.lastEvent.text.slice(0, 240) : undefined
  pushEvent({
    type: 'refresh_last_request_clicked',
    ts: nowIso(),
    location: args.location,
    years: args.years,
    last_event: args.lastEvent
      ? { timestamp: args.lastEvent.timestamp, speaker: args.lastEvent.speaker, text_preview: textPreview ?? '' }
      : undefined,
  })
}

export function recordRunAiClicked(): void {
  pushEvent({ type: 'run_ai_clicked', ts: nowIso() })
}

export function recordBoardExportRequested(): void {
  pushEvent({ type: 'board_export_requested', ts: nowIso() })
}

export function recordBoardExportDownloaded(filename: string): void {
  pushEvent({ type: 'board_export_downloaded', ts: nowIso(), filename })
}

export function recordBoardImportSent(filename?: string): void {
  pushEvent({ type: 'board_import_sent', ts: nowIso(), filename })
}

export function recordBoardImportError(args: {
  stage: 'parse' | 'send' | 'server'
  message: string
  filename?: string
}): void {
  pushEvent({ type: 'board_import_error', ts: nowIso(), stage: args.stage, message: args.message, filename: args.filename })
}
