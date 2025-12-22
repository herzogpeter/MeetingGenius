import './App.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { TranscriptPanel } from './components/TranscriptPanel'
import { Whiteboard } from './components/Whiteboard'
import type { TranscriptEvent } from './contracts'
import { useBoardSocket } from './hooks/useBoardSocket'
import {
  clearSessionTelemetry,
  downloadSessionTelemetryJson,
  recordAssumptionsChanged,
  recordRefreshLastRequestClicked,
} from './telemetry/sessionTelemetry'

const YEARS_STORAGE_KEY = 'mg.assumptions.years'
const YEAR_OPTIONS = [5, 10, 15] as const

function parseYears(raw: string | null): number | null {
  if (!raw) return null
  const num = Number.parseInt(raw, 10)
  if (Number.isNaN(num)) return null
  return YEAR_OPTIONS.includes(num as (typeof YEAR_OPTIONS)[number]) ? num : null
}

function App() {
  const [transcript, setTranscript] = useState<TranscriptEvent[]>([])
  const [locallyDismissed, setLocallyDismissed] = useState<Set<string>>(() => new Set())
  const [location, setLocation] = useState<string>('Seattle')
  const [locationDraft, setLocationDraft] = useState<string>('Seattle')
  const [years, setYears] = useState<number>(() => {
    try {
      return parseYears(window.localStorage.getItem(YEARS_STORAGE_KEY)) ?? 10
    } catch {
      return 10
    }
  })
  const [lastFinalTranscriptEventSent, setLastFinalTranscriptEventSent] = useState<TranscriptEvent | null>(
    null,
  )
  const [clientStatusMessage, setClientStatusMessage] = useState<string | null>(null)
  const clearStatusTimerRef = useRef<number | null>(null)

  const {
    connectionState,
    lastStatusMessage,
    boardState,
    sendTranscriptEvent,
    sendSessionContext,
    sendClientBoardAction,
    sendReset,
  } = useBoardSocket()

  useEffect(() => {
    try {
      window.localStorage.setItem(YEARS_STORAGE_KEY, String(years))
    } catch {
      // ignore local storage failures
    }
  }, [years])

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

  const showClientStatus = (message: string) => {
    setClientStatusMessage(message)
    if (clearStatusTimerRef.current) window.clearTimeout(clearStatusTimerRef.current)
    clearStatusTimerRef.current = window.setTimeout(() => {
      setClientStatusMessage(null)
    }, 3000)
  }

  const applyLocation = () => {
    const nextLocation = locationDraft.trim()
    if (!nextLocation) return
    const sent = sendSessionContext(nextLocation)
    if (!sent) return

    if (nextLocation !== location) {
      recordAssumptionsChanged({
        changes: { location: { prev: location, next: nextLocation } },
        current: { location: nextLocation, years },
      })
    }

    setLocation(nextLocation)
    setLocationDraft(nextLocation)
    showClientStatus(`Location set: ${nextLocation}`)
  }

  const refreshLastRequest = () => {
    if (connectionState !== 'open') return
    if (!lastFinalTranscriptEventSent) return

    const baseText = lastFinalTranscriptEventSent.text
      .replace(/\s*\(Use location=[^,]+,\s*years=\d+\.\)\s*$/u, '')
      .trim()

    const suffix = `(Use location=${location}, years=${years}.)`
    const event: TranscriptEvent = {
      timestamp: new Date().toISOString(),
      speaker: lastFinalTranscriptEventSent.speaker,
      text: `${baseText} ${suffix}`.trim(),
      is_final: true,
    }

    recordRefreshLastRequestClicked({
      location,
      years,
      lastEvent: lastFinalTranscriptEventSent,
    })

    sendTranscriptEvent(event)
    setTranscript((prev) => [...prev, event])
    setLastFinalTranscriptEventSent(event)
    showClientStatus('Refreshed last request')
  }

  return (
    <div className="mgApp">
      <header className="mgHeader">
        <div className="mgHeaderTitle">MeetingGenius</div>
        <div className="mgHeaderMeta">
          <div className="mgHeaderTopRow">
            <div className={`mgPill mgPill--${connectionState}`}>WS: {connectionState}</div>
            {statusMessage ? <div className="mgStatus">{statusMessage}</div> : null}
            <div className="mgHeaderActions">
              <button className="mgButton mgButton--small" onClick={downloadSessionTelemetryJson}>
                Export session JSON
              </button>
              <button className="mgButton mgButton--small" onClick={clearSessionTelemetry}>
                Clear session
              </button>
            </div>
          </div>

          <div className="mgHeaderAssumptions">
            <div className="mgHeaderAssumptionsLabel">Assumptions</div>
            <div className="mgHeaderAssumptionsChips">
              <div className="mgPill mgPill--idle">Location: {location}</div>
              <div className="mgPill mgPill--idle">Years: {years}</div>
            </div>
            <div className="mgHeaderAssumptionsControls">
              <div className="mgHeaderLocation">
                <label className="mgHeaderLabel" htmlFor="mgLocationInput">
                  Location
                </label>
                <input
                  id="mgLocationInput"
                  className="mgInput mgInput--small"
                  value={locationDraft}
                  onChange={(e) => setLocationDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') applyLocation()
                  }}
                />
                <button
                  className="mgButton mgButton--small"
                  disabled={connectionState !== 'open'}
                  onClick={applyLocation}
                >
                  Set
                </button>
              </div>

              <div className="mgHeaderYears">
                <label className="mgHeaderLabel" htmlFor="mgYearsSelect">
                  Years
                </label>
                <select
                  id="mgYearsSelect"
                  className="mgInput mgInput--small mgSelect--small"
                  value={years}
                  onChange={(e) => {
                    const nextYears = Number.parseInt(e.target.value, 10)
                    if (Number.isNaN(nextYears) || nextYears === years) return
                    recordAssumptionsChanged({
                      changes: { years: { prev: years, next: nextYears } },
                      current: { location, years: nextYears },
                    })
                    setYears(nextYears)
                    showClientStatus(`Years set: ${nextYears}`)
                  }}
                >
                  {YEAR_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <button
                className="mgButton mgButton--small"
                disabled={connectionState !== 'open' || !lastFinalTranscriptEventSent}
                onClick={refreshLastRequest}
              >
                Refresh last request
              </button>
            </div>
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
              if (event.is_final) setLastFinalTranscriptEventSent(event)
            }}
            onReset={() => {
              sendReset()
              setTranscript([])
              setLocallyDismissed(new Set())
              setLastFinalTranscriptEventSent(null)
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
