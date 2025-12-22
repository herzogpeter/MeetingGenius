import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { BoardState, IncomingMessage, OutgoingMessage, TranscriptEvent } from '../contracts'
import { emptyBoardState } from '../contracts'
import {
  recordBoardActionsReceived,
  recordConnectionStateChanged,
  recordTranscriptEventSent,
} from '../telemetry/sessionTelemetry'

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'

const WS_URL: string = (import.meta.env.VITE_WS_URL as string | undefined) ?? 'ws://localhost:8000/ws'

export function useBoardSocket(): {
  connectionState: ConnectionState
  lastStatusMessage: string | null
  boardState: BoardState
  sendTranscriptEvent: (event: TranscriptEvent) => void
  sendSessionContext: (args: { defaultLocation: string; noBrowse: boolean; years?: number; month?: number }) => boolean
  sendClientBoardAction: (action: unknown) => void
  sendReset: () => void
} {
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const shouldReconnectRef = useRef(true)

  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')
  const [lastStatusMessage, setLastStatusMessage] = useState<string | null>(null)
  const [boardState, setBoardState] = useState<BoardState>(() => emptyBoardState())

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
    (args: { defaultLocation: string; noBrowse: boolean; years?: number; month?: number }) =>
      sendMessage({
        type: 'set_session_context',
        default_location: args.defaultLocation,
        no_browse: args.noBrowse,
        years: args.years,
        month: args.month,
      }),
    [sendMessage],
  )

  const sendClientBoardAction = useCallback((action: unknown) => {
    sendMessage({ type: 'client_board_action', action })
  }, [sendMessage])

  const sendReset = useCallback(() => {
    sendMessage({ type: 'reset' })
    setLastStatusMessage(null)
    setBoardState(emptyBoardState())
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

        if (message.type === 'board_actions') {
          recordBoardActionsReceived(message)
          setBoardState(message.state ?? emptyBoardState())
          return
        }
      } catch {
        // ignore malformed messages in prototype
      }
    })

    socket.addEventListener('close', () => {
      setConnectionState('closed')
      recordConnectionStateChanged('closed')
      if (shouldReconnectRef.current) {
        reconnectTimerRef.current = window.setTimeout(() => connectSocket(), 1000)
      }
    })

    socket.addEventListener('error', () => {
      setConnectionState('error')
      recordConnectionStateChanged('error')
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
      boardState,
      sendTranscriptEvent,
      sendSessionContext,
      sendClientBoardAction,
      sendReset,
    }),
    [
      boardState,
      connectionState,
      lastStatusMessage,
      sendClientBoardAction,
      sendReset,
      sendSessionContext,
      sendTranscriptEvent,
    ],
  )
}
