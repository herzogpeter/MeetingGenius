import './App.css'
import { useMemo, useState } from 'react'
import { TranscriptPanel } from './components/TranscriptPanel'
import { Whiteboard } from './components/Whiteboard'
import type { TranscriptEvent } from './contracts'
import { useBoardSocket } from './hooks/useBoardSocket'
import { clearSessionTelemetry, downloadSessionTelemetryJson } from './telemetry/sessionTelemetry'

function App() {
  const [transcript, setTranscript] = useState<TranscriptEvent[]>([])
  const [locallyDismissed, setLocallyDismissed] = useState<Set<string>>(() => new Set())

  const {
    connectionState,
    lastStatusMessage,
    boardState,
    sendTranscriptEvent,
    sendClientBoardAction,
    sendReset,
  } = useBoardSocket()

  const effectiveDismissed = useMemo(() => {
    const dismissed = new Set<string>([...locallyDismissed])
    for (const cardId of Object.keys(boardState.dismissed ?? {})) dismissed.add(cardId)
    return dismissed
  }, [boardState.dismissed, locallyDismissed])

  return (
    <div className="mgApp">
      <header className="mgHeader">
        <div className="mgHeaderTitle">MeetingGenius</div>
        <div className="mgHeaderMeta">
          <div className={`mgPill mgPill--${connectionState}`}>
            WS: {connectionState}
          </div>
          {lastStatusMessage ? <div className="mgStatus">{lastStatusMessage}</div> : null}
          <div className="mgHeaderActions">
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
            sendClientBoardAction={sendClientBoardAction}
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
