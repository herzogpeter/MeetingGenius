import './App.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Mindmap } from './components/Mindmap'
import { TranscriptPanel } from './components/TranscriptPanel'
import { Whiteboard } from './components/Whiteboard'
import type { BoardState, TranscriptEvent } from './contracts'
import { useBoardSocket } from './hooks/useBoardSocket'
import {
  clearSessionTelemetry,
  downloadSessionTelemetryJson,
  recordAssumptionsChanged,
  recordBoardExportDownloaded,
  recordBoardExportRequested,
  recordBoardImportError,
  recordBoardImportSent,
  recordRefreshLastRequestClicked,
  recordRunAiClicked,
} from './telemetry/sessionTelemetry'

const YEARS_STORAGE_KEY = 'mg.assumptions.years'
const NO_BROWSE_STORAGE_KEY = 'mg.assumptions.noBrowse'
const MINDMAP_AI_STORAGE_KEY = 'mg.assumptions.mindmapAi'
const VIEW_MODE_STORAGE_KEY = 'mg.viewMode'
const YEAR_OPTIONS = [5, 10, 15] as const

function parseYears(raw: string | null): number | null {
  if (!raw) return null
  const num = Number.parseInt(raw, 10)
  if (Number.isNaN(num)) return null
  return YEAR_OPTIONS.includes(num as (typeof YEAR_OPTIONS)[number]) ? num : null
}

function parseBool(raw: string | null): boolean | null {
  if (!raw) return null
  const normalized = raw.trim().toLowerCase()
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false
  return null
}

function nowIsoForFilename(): string {
  return new Date().toISOString().replace(/[:.]/g, '-')
}

function downloadJsonFile(payload: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function looksLikeBoardState(value: unknown): value is BoardState {
  if (!isPlainObject(value)) return false
  return isPlainObject(value.cards) && isPlainObject(value.layout) && isPlainObject(value.dismissed)
}

function App() {
  const [transcript, setTranscript] = useState<TranscriptEvent[]>([])
  const [locallyDismissed, setLocallyDismissed] = useState<Set<string>>(() => new Set())
  const [viewMode, setViewMode] = useState<'whiteboard' | 'mindmap'>(() => {
    try {
      const raw = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY)
      return raw === 'mindmap' ? 'mindmap' : 'whiteboard'
    } catch {
      return 'whiteboard'
    }
  })
  const [location, setLocation] = useState<string>('Seattle')
  const [locationDraft, setLocationDraft] = useState<string>('Seattle')
  const [years, setYears] = useState<number>(() => {
    try {
      return parseYears(window.localStorage.getItem(YEARS_STORAGE_KEY)) ?? 10
    } catch {
      return 10
    }
  })
  const [noBrowse, setNoBrowse] = useState<boolean>(() => {
    try {
      return parseBool(window.localStorage.getItem(NO_BROWSE_STORAGE_KEY)) ?? false
    } catch {
      return false
    }
  })
  const [mindmapAi, setMindmapAi] = useState<boolean>(() => {
    try {
      return parseBool(window.localStorage.getItem(MINDMAP_AI_STORAGE_KEY)) ?? true
    } catch {
      return true
    }
  })
  const [lastFinalTranscriptEventSent, setLastFinalTranscriptEventSent] = useState<TranscriptEvent | null>(
    null,
  )
  const [clientStatusMessage, setClientStatusMessage] = useState<string | null>(null)
  const clearStatusTimerRef = useRef<number | null>(null)
  const initialContextSentRef = useRef(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)
  const pendingImportRef = useRef<{ filename?: string } | null>(null)
  const pendingImportTimerRef = useRef<number | null>(null)

  const {
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
  } = useBoardSocket()

  useEffect(() => {
    try {
      window.localStorage.setItem(YEARS_STORAGE_KEY, String(years))
    } catch {
      // ignore local storage failures
    }
  }, [years])

  useEffect(() => {
    try {
      window.localStorage.setItem(NO_BROWSE_STORAGE_KEY, String(noBrowse))
    } catch {
      // ignore local storage failures
    }
  }, [noBrowse])

  useEffect(() => {
    try {
      window.localStorage.setItem(MINDMAP_AI_STORAGE_KEY, String(mindmapAi))
    } catch {
      // ignore local storage failures
    }
  }, [mindmapAi])

  useEffect(() => {
    try {
      window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode)
    } catch {
      // ignore local storage failures
    }
  }, [viewMode])

  useEffect(() => {
    return () => {
      if (clearStatusTimerRef.current) window.clearTimeout(clearStatusTimerRef.current)
      if (pendingImportTimerRef.current) window.clearTimeout(pendingImportTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (connectionState !== 'open') {
      initialContextSentRef.current = false
      return
    }
    if (initialContextSentRef.current) return
    const sent = sendSessionContext({ defaultLocation: location, noBrowse, years, mindmapAi })
    if (sent) initialContextSentRef.current = true
  }, [connectionState, location, mindmapAi, noBrowse, sendSessionContext, years])

  const effectiveDismissed = useMemo(() => {
    const dismissed = new Set<string>([...locallyDismissed])
    for (const cardId of Object.keys(boardState.dismissed ?? {})) dismissed.add(cardId)
    return dismissed
  }, [boardState.dismissed, locallyDismissed])

  const statusMessage = clientStatusMessage ?? lastStatusMessage

  const showClientStatus = useCallback((message: string) => {
    setClientStatusMessage(message)
    if (clearStatusTimerRef.current) window.clearTimeout(clearStatusTimerRef.current)
    clearStatusTimerRef.current = window.setTimeout(() => {
      setClientStatusMessage(null)
    }, 3000)
  }, [])

  useEffect(() => {
    if (!lastBoardExport) return
    const filename = `meetinggenius-board-${nowIsoForFilename()}.json`
    downloadJsonFile(lastBoardExport, filename)
    recordBoardExportDownloaded(filename)
    window.setTimeout(() => showClientStatus(`Board exported: ${filename}`), 0)
  }, [lastBoardExport, showClientStatus])

  useEffect(() => {
    if (!lastError) return
    const pending = pendingImportRef.current
    if (!pending) return
    recordBoardImportError({ stage: 'server', message: lastError.message, filename: pending.filename })
    pendingImportRef.current = null
  }, [lastError])

  const applyLocation = () => {
    const nextLocation = locationDraft.trim()
    if (!nextLocation) return
    const sent = sendSessionContext({ defaultLocation: nextLocation, noBrowse, years, mindmapAi })
    if (!sent) return

    if (nextLocation !== location) {
      recordAssumptionsChanged({
        changes: { location: { prev: location, next: nextLocation } },
        current: { location: nextLocation, years, no_browse: noBrowse, mindmap_ai: mindmapAi },
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

  const runAiNow = () => {
    if (connectionState !== 'open') return
    recordRunAiClicked()
    sendRunAi()
  }

  const exportBoard = () => {
    if (connectionState !== 'open') return
    recordBoardExportRequested()
    const sent = sendExportBoard()
    if (sent) showClientStatus('Exporting board…')
  }

  const onImportFileSelected = async (file: File) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(await file.text()) as unknown
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Invalid JSON'
      recordBoardImportError({ stage: 'parse', message, filename: file.name })
      showClientStatus(`Import failed: ${message}`)
      return
    }

    let boardStateCandidate: unknown = parsed
    let defaultLocationFromFile: string | null | undefined
    let noBrowseFromFile: boolean | null | undefined

    if (isPlainObject(parsed) && parsed.type === 'board_export') {
      boardStateCandidate = parsed.state
      if ('default_location' in parsed) defaultLocationFromFile = parsed.default_location as string | null | undefined
      if ('no_browse' in parsed) noBrowseFromFile = parsed.no_browse as boolean | null | undefined
    }

    if (!looksLikeBoardState(boardStateCandidate)) {
      recordBoardImportError({ stage: 'parse', message: 'Unrecognized board export format', filename: file.name })
      showClientStatus('Import failed: unrecognized board export format')
      return
    }

    const sent = sendImportBoard({
      state: boardStateCandidate,
      ...(defaultLocationFromFile !== undefined ? { defaultLocation: defaultLocationFromFile } : {}),
      ...(noBrowseFromFile !== undefined ? { noBrowse: noBrowseFromFile } : {}),
    })
    if (!sent) {
      recordBoardImportError({ stage: 'send', message: 'WebSocket not connected', filename: file.name })
      showClientStatus('Import failed: WebSocket not connected')
      return
    }

    recordBoardImportSent(file.name)
    pendingImportRef.current = { filename: file.name }
    if (pendingImportTimerRef.current) window.clearTimeout(pendingImportTimerRef.current)
    pendingImportTimerRef.current = window.setTimeout(() => {
      pendingImportRef.current = null
      pendingImportTimerRef.current = null
    }, 5000)

    if (typeof defaultLocationFromFile === 'string' && defaultLocationFromFile.trim()) {
      setLocation(defaultLocationFromFile.trim())
      setLocationDraft(defaultLocationFromFile.trim())
    }
    if (typeof noBrowseFromFile === 'boolean') {
      setNoBrowse(noBrowseFromFile)
    }

    showClientStatus(`Import sent: ${file.name}`)
  }

  return (
    <div className="mgApp">
      <header className="mgHeader">
        <div className="mgHeaderTitle">MeetingGenius</div>
        <div className="mgHeaderMeta">
          <div className="mgHeaderTopRow">
            <div className={`mgPill mgPill--${connectionState}`}>WS: {connectionState}</div>
            {mindmapStatus === 'running' ? <div className="mgPill mgPill--running">Mindmap: updating…</div> : null}
            {statusMessage ? <div className="mgStatus">{statusMessage}</div> : null}
            <div className="mgHeaderActions">
              <button
                className="mgButton mgButton--small"
                onClick={() => setViewMode((prev) => (prev === 'whiteboard' ? 'mindmap' : 'whiteboard'))}
              >
                View: {viewMode === 'whiteboard' ? 'Whiteboard' : 'Mindmap'}
              </button>
              <button className="mgButton mgButton--small" disabled={connectionState !== 'open'} onClick={runAiNow}>
                Run AI now
              </button>
              <button className="mgButton mgButton--small" disabled={connectionState !== 'open'} onClick={exportBoard}>
                Export board
              </button>
              <button
                className="mgButton mgButton--small"
                disabled={connectionState !== 'open'}
                onClick={() => importInputRef.current?.click()}
              >
                Import board
              </button>
              <button className="mgButton mgButton--small" onClick={downloadSessionTelemetryJson}>
                Export session JSON
              </button>
              <button className="mgButton mgButton--small" onClick={clearSessionTelemetry}>
                Clear session
              </button>
              <input
                ref={importInputRef}
                type="file"
                accept="application/json"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (!file) return
                  void onImportFileSelected(file)
                }}
              />
            </div>
          </div>

          <div className="mgHeaderAssumptions">
            <div className="mgHeaderAssumptionsLabel">Assumptions</div>
            <div className="mgHeaderAssumptionsChips">
              <div className="mgPill mgPill--idle">Location: {location}</div>
              <div className="mgPill mgPill--idle">Years: {years}</div>
              <div className="mgPill mgPill--idle">External research: {noBrowse ? 'Off' : 'On'}</div>
              <div className="mgPill mgPill--idle">Mindmap AI: {mindmapAi ? 'On' : 'Off'}</div>
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
                      current: { location, years: nextYears, no_browse: noBrowse, mindmap_ai: mindmapAi },
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

              <div className="mgHeaderResearch">
                <label className="mgHeaderLabel" htmlFor="mgResearchSelect">
                  External research
                </label>
                <select
                  id="mgResearchSelect"
                  className="mgInput mgInput--small mgSelect--medium"
                  value={noBrowse ? 'off' : 'on'}
                  onChange={(e) => {
                    const nextNoBrowse = e.target.value === 'off'
                    if (nextNoBrowse === noBrowse) return
                    recordAssumptionsChanged({
                      changes: { no_browse: { prev: noBrowse, next: nextNoBrowse } },
                      current: { location, years, no_browse: nextNoBrowse, mindmap_ai: mindmapAi },
                    })
                    setNoBrowse(nextNoBrowse)
                    const sent = sendSessionContext({
                      defaultLocation: location,
                      noBrowse: nextNoBrowse,
                      years,
                      mindmapAi,
                    })
                    if (sent) showClientStatus(`External research ${nextNoBrowse ? 'Off' : 'On'}`)
                  }}
                >
                  <option value="on">On</option>
                  <option value="off">Off</option>
                </select>
              </div>

              <div className="mgHeaderMindmapAi">
                <label className="mgHeaderLabel" htmlFor="mgMindmapAiSelect">
                  Mindmap AI
                </label>
                <select
                  id="mgMindmapAiSelect"
                  className="mgInput mgInput--small mgSelect--medium"
                  value={mindmapAi ? 'on' : 'off'}
                  onChange={(e) => {
                    const nextMindmapAi = e.target.value === 'on'
                    if (nextMindmapAi === mindmapAi) return
                    recordAssumptionsChanged({
                      changes: { mindmap_ai: { prev: mindmapAi, next: nextMindmapAi } },
                      current: { location, years, no_browse: noBrowse, mindmap_ai: nextMindmapAi },
                    })
                    setMindmapAi(nextMindmapAi)
                    const sent = sendSessionContext({
                      defaultLocation: location,
                      noBrowse,
                      years,
                      mindmapAi: nextMindmapAi,
                    })
                    if (sent) showClientStatus(`Mindmap AI ${nextMindmapAi ? 'On' : 'Off'}`)
                  }}
                >
                  <option value="on">On</option>
                  <option value="off">Off</option>
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

        <section className={`mgPanel ${viewMode === 'whiteboard' ? 'mgPanel--whiteboard' : 'mgPanel--mindmap'}`}>
          {viewMode === 'whiteboard' ? (
            <Whiteboard
              boardState={boardState}
              dismissed={effectiveDismissed}
              sendClientBoardAction={sendClientBoardAction}
              onDismiss={(cardId) => {
                setLocallyDismissed((prev) => new Set(prev).add(cardId))
              }}
            />
          ) : (
            <Mindmap mindmapState={mindmapState} sendClientMindmapAction={sendClientMindmapAction} />
          )}
        </section>
      </main>
    </div>
  )
}

export default App
