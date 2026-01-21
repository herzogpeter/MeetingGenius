import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  BoardState,
  IncomingBoardExportMessage,
  IncomingErrorMessage,
  IncomingMessage,
  MindmapAction,
  MindmapStatus,
  MindmapState,
  OutgoingMessage,
  TranscriptEvent,
} from '../contracts'
import { emptyBoardState, emptyMindmapState } from '../contracts'
import {
  recordBoardActionsReceived,
  recordConnectionStateChanged,
  recordServerErrorReceived,
  recordTranscriptEventSent,
} from '../telemetry/sessionTelemetry'

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'

const DEFAULT_WS_HOST =
  window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const WS_URL: string =
  (import.meta.env.VITE_WS_URL as string | undefined) ?? `ws://${DEFAULT_WS_HOST}:8000/ws`

export function useBoardSocket(): {
  connectionState: ConnectionState
  lastStatusMessage: string | null
  lastError: IncomingErrorMessage | null
  lastBoardExport: IncomingBoardExportMessage | null
  boardState: BoardState
  mindmapState: MindmapState
  mindmapStatus: MindmapStatus
  sendTranscriptEvent: (event: TranscriptEvent) => void
  sendSessionContext: (args: {
    defaultLocation: string
    noBrowse: boolean
    years?: number
    month?: number
    mindmapAi?: boolean
  }) => boolean
  sendExportBoard: () => boolean
  sendImportBoard: (args: {
    state: BoardState
    defaultLocation?: string | null
    noBrowse?: boolean | null
  }) => boolean
  sendRunAi: () => boolean
  sendClientBoardAction: (action: unknown) => void
  sendClientMindmapAction: (action: MindmapAction) => void
  sendReset: () => void
} {
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const shouldReconnectRef = useRef(true)

  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')
  const [lastStatusMessage, setLastStatusMessage] = useState<string | null>(null)
  const [lastError, setLastError] = useState<IncomingErrorMessage | null>(null)
  const [lastBoardExport, setLastBoardExport] = useState<IncomingBoardExportMessage | null>(null)
  const [boardState, setBoardState] = useState<BoardState>(() => emptyBoardState())
  const [mindmapState, setMindmapState] = useState<MindmapState>(() => emptyMindmapState())
  const [mindmapStatus, setMindmapStatus] = useState<MindmapStatus>('idle')

  const sendMessage = useCallback((message: OutgoingMessage) => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    socket.send(JSON.stringify(message))
    return true
  }, [])

  const sendTranscriptEvent = useCallback(
    (event: TranscriptEvent) => {
      if (sendMessage({ type: 'transcript_event', event })) {
        recordTranscriptEventSent(event)
      }
    },
    [sendMessage],
  )

  const sendSessionContext = useCallback(
    (args: { defaultLocation: string; noBrowse: boolean; years?: number; month?: number; mindmapAi?: boolean }) =>
      sendMessage({
        type: 'set_session_context',
        default_location: args.defaultLocation,
        no_browse: args.noBrowse,
        years: args.years,
        month: args.month,
        mindmap_ai: args.mindmapAi,
      }),
    [sendMessage],
  )

  const sendExportBoard = useCallback(() => sendMessage({ type: 'export_board' }), [sendMessage])

  const sendImportBoard = useCallback(
    (args: { state: BoardState; defaultLocation?: string | null; noBrowse?: boolean | null }) => {
      const payload: OutgoingMessage = {
        type: 'import_board',
        state: args.state,
        ...(args.defaultLocation !== undefined ? { default_location: args.defaultLocation } : {}),
        ...(args.noBrowse !== undefined ? { no_browse: args.noBrowse } : {}),
      }
      return sendMessage(payload)
    },
    [sendMessage],
  )

  const sendRunAi = useCallback(() => sendMessage({ type: 'run_ai' }), [sendMessage])

  const sendClientBoardAction = useCallback((action: unknown) => {
    sendMessage({ type: 'client_board_action', action })
  }, [sendMessage])

  const sendClientMindmapAction = useCallback((action: MindmapAction) => {
    sendMessage({ type: 'client_mindmap_action', action })
  }, [sendMessage])

  const sendReset = useCallback(() => {
    sendMessage({ type: 'reset' })
    setLastStatusMessage(null)
    setBoardState(emptyBoardState())
    setMindmapState(emptyMindmapState())
    setMindmapStatus('idle')
  }, [sendMessage])

  const connect = useCallback(function connectSocket() {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }

    setConnectionState('connecting')
    recordConnectionStateChanged('connecting')
    const socket = new WebSocket(WS_URL)
    socketRef.current = socket

    socket.addEventListener('open', () => {
      setConnectionState('open')
      setLastStatusMessage(null)
      setLastError(null)
      setMindmapStatus('idle')
      recordConnectionStateChanged('open')
    })

    socket.addEventListener('message', (event) => {
      try {
        const parsed: unknown = JSON.parse(String(event.data))
        const message = parsed as IncomingMessage
        if (!message || typeof message !== 'object' || !('type' in message)) return

        if (message.type === 'status') {
          setLastStatusMessage(message.message)
          return
        }

        if (message.type === 'error') {
          setLastError(message)
          setLastStatusMessage(message.message)
          recordServerErrorReceived(message)
          return
        }

        if (message.type === 'board_actions') {
          recordBoardActionsReceived(message)
          setBoardState(message.state ?? emptyBoardState())
          return
        }

        if (message.type === 'mindmap_actions') {
          setMindmapState(message.state ?? emptyMindmapState())
          return
        }

        if (message.type === 'mindmap_status') {
          setMindmapStatus(message.status ?? 'idle')
          return
        }

        if (message.type === 'board_export') {
          setLastBoardExport(message)
          return
        }
      } catch {
        // ignore malformed messages in prototype
      }
    })

    socket.addEventListener('close', () => {
      setConnectionState('closed')
      recordConnectionStateChanged('closed')
      setMindmapStatus('idle')
      if (shouldReconnectRef.current) {
        reconnectTimerRef.current = window.setTimeout(() => connectSocket(), 1000)
      }
    })

    socket.addEventListener('error', () => {
      setConnectionState('error')
      recordConnectionStateChanged('error')
      setMindmapStatus('idle')
    })
  }, [])

  useEffect(() => {
    shouldReconnectRef.current = true
    connect()
    return () => {
      shouldReconnectRef.current = false
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current)
      socketRef.current?.close()
    }
  }, [connect])

  return useMemo(
    () => ({
      connectionState,
      lastStatusMessage,
      lastError,
      lastBoardExport,
      boardState,
      mindmapState,
      mindmapStatus,
      sendTranscriptEvent,
      sendSessionContext,
      sendExportBoard,
      sendImportBoard,
      sendRunAi,
      sendClientBoardAction,
      sendClientMindmapAction,
      sendReset,
    }),
    [
      boardState,
      connectionState,
      lastBoardExport,
      lastError,
      lastStatusMessage,
      mindmapState,
      mindmapStatus,
      sendClientBoardAction,
      sendClientMindmapAction,
      sendExportBoard,
      sendImportBoard,
      sendReset,
      sendRunAi,
      sendSessionContext,
      sendTranscriptEvent,
    ],
  )
}
