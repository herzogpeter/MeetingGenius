import './App.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { TranscriptPanel } from './components/TranscriptPanel'
import { Whiteboard } from './components/Whiteboard'
import type { TranscriptEvent } from './contracts'
import { useBoardSocket } from './hooks/useBoardSocket'
import { clearSessionTelemetry, downloadSessionTelemetryJson } from './telemetry/sessionTelemetry'

function App() {
  const [transcript, setTranscript] = useState<TranscriptEvent[]>([])
  const [locallyDismissed, setLocallyDismissed] = useState<Set<string>>(() => new Set())
  const [defaultLocation, setDefaultLocation] = useState<string>('Seattle')
  const [clientStatusMessage, setClientStatusMessage] = useState<string | null>(null)
  const clearStatusTimerRef = useRef<number | null>(null)

  const {
    connectionState,
    lastStatusMessage,
    boardState,
    sendTranscriptEvent,
    sendSessionContext,
    sendReset,
  } = useBoardSocket()

  useEffect(() => {
    return () => {
      if (clearStatusTimerRef.current) window.clearTimeout(clearStatusTimerRef.current)
    }
  }, [])

  const effectiveDismissed = useMemo(() => {
    const dismissed = new Set<string>([...locallyDismissed])
    for (const cardId of Object.keys(boardState.dismissed ?? {})) dismissed.add(cardId)
    return dismissed
  }, [boardState.dismissed, locallyDismissed])

  const statusMessage = clientStatusMessage ?? lastStatusMessage

  return (
    <div className="mgApp">
      <header className="mgHeader">
        <div className="mgHeaderTitle">MeetingGenius</div>
        <div className="mgHeaderMeta">
          <div className={`mgPill mgPill--${connectionState}`}>
            WS: {connectionState}
          </div>
          {statusMessage ? <div className="mgStatus">{statusMessage}</div> : null}
          <div className="mgHeaderActions">
            <div className="mgHeaderLocation">
              <label className="mgHeaderLabel" htmlFor="mgLocationInput">
                Location
              </label>
              <input
                id="mgLocationInput"
                className="mgInput mgInput--small"
                value={defaultLocation}
                onChange={(e) => setDefaultLocation(e.target.value)}
              />
              <button
                className="mgButton mgButton--small"
                disabled={connectionState !== 'open'}
                onClick={() => {
                  const nextLocation = defaultLocation.trim()
                  if (!nextLocation) return
                  if (sendSessionContext(nextLocation)) {
                    setDefaultLocation(nextLocation)
                    setClientStatusMessage(`Location set: ${nextLocation}`)
                    if (clearStatusTimerRef.current) window.clearTimeout(clearStatusTimerRef.current)
                    clearStatusTimerRef.current = window.setTimeout(() => {
                      setClientStatusMessage(null)
                    }, 3000)
                  }
                }}
              >
                Set
              </button>
            </div>
            <button className="mgButton mgButton--small" onClick={downloadSessionTelemetryJson}>
              Export session JSON
            </button>
            <button className="mgButton mgButton--small" onClick={clearSessionTelemetry}>
              Clear session
            </button>
          </div>
        </div>
      </header>

      <main className="mgMain">
        <aside className="mgPanel mgPanel--transcript">
          <TranscriptPanel
            connectionState={connectionState}
            transcript={transcript}
            onSend={(event) => {
              if (connectionState !== 'open') return
              sendTranscriptEvent(event)
              setTranscript((prev) => [...prev, event])
            }}
            onReset={() => {
              sendReset()
              setTranscript([])
              setLocallyDismissed(new Set())
            }}
          />
        </aside>

        <section className="mgPanel mgPanel--whiteboard">
          <Whiteboard
            boardState={boardState}
            dismissed={effectiveDismissed}
            onDismiss={(cardId) => {
              setLocallyDismissed((prev) => new Set(prev).add(cardId))
            }}
          />
        </section>
      </main>
    </div>
  )
}

export default App
