import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { TranscriptEvent } from '../contracts'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'

type ReplayStatus = 'idle' | 'running' | 'paused' | 'done'

function countWords(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length
}

function splitIntoSentences(text: string): string[] {
  const normalized = text.replace(/\r\n/g, '\n')
  const lines = normalized
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  const out: string[] = []
  for (const line of lines) {
    const matches = line.match(/[^.!?]+[.!?]+|[^.!?]+$/g)
    if (!matches) {
      out.push(line)
      continue
    }
    for (const m of matches) {
      const s = m.trim()
      if (s) out.push(s)
    }
  }
  return out
}

function chunkSentences(sentences: string[], maxWords: number): string[] {
  const cappedMaxWords = Number.isFinite(maxWords) ? Math.max(1, Math.floor(maxWords)) : 24
  const chunks: string[] = []
  let current = ''
  let currentWords = 0

  for (const sentence of sentences) {
    const words = countWords(sentence)
    if (!current) {
      current = sentence
      currentWords = words
      continue
    }

    if (currentWords + words <= cappedMaxWords) {
      current = `${current} ${sentence}`
      currentWords += words
      continue
    }

    chunks.push(current)
    current = sentence
    currentWords = words
  }

  if (current) chunks.push(current)
  return chunks
}

export function TranscriptPanel(props: {
  connectionState: 'connecting' | 'open' | 'closed' | 'error'
  transcript: TranscriptEvent[]
  onSend: (event: TranscriptEvent) => void
  onReset: () => void
}) {
  const [speaker, setSpeaker] = useState('User')
  const [text, setText] = useState('')
  const [sendInterimResults, setSendInterimResults] = useState(false)
  const [language, setLanguage] = useState('en-US')

  const [replayStatus, setReplayStatus] = useState<ReplayStatus>('idle')
  const [replayText, setReplayText] = useState('')
  const [replayAsFinal, setReplayAsFinal] = useState(false)
  const [replayWpm, setReplayWpm] = useState(155)
  const [replayMaxWords, setReplayMaxWords] = useState(22)
  const [replayMinSeconds, setReplayMinSeconds] = useState(1.4)
  const [replayProgress, setReplayProgress] = useState<{ index: number; total: number }>({ index: 0, total: 0 })
  const replayTimerRef = useRef<number | null>(null)

  const replayChunks = useMemo(() => {
    const sentences = splitIntoSentences(replayText)
    return chunkSentences(sentences, replayMaxWords)
  }, [replayMaxWords, replayText])

  const canReplay = useMemo(
    () => props.connectionState === 'open' && replayChunks.length > 0,
    [props.connectionState, replayChunks.length],
  )

  const stopReplay = useCallback(() => {
    if (replayTimerRef.current !== null) window.clearTimeout(replayTimerRef.current)
    replayTimerRef.current = null
    setReplayStatus('idle')
    setReplayProgress({ index: 0, total: replayChunks.length })
  }, [replayChunks.length])

  const startReplayFromIndex = useCallback(
    (startIndex: number) => {
      if (props.connectionState !== 'open') return
      if (replayChunks.length === 0) return

      if (replayTimerRef.current !== null) window.clearTimeout(replayTimerRef.current)
      replayTimerRef.current = null

      setReplayStatus('running')
      setReplayProgress({ index: startIndex, total: replayChunks.length })

      const sendNext = (idx: number) => {
        if (idx >= replayChunks.length) {
          replayTimerRef.current = null
          setReplayStatus('done')
          setReplayProgress({ index: replayChunks.length, total: replayChunks.length })
          return
        }

        const chunk = replayChunks[idx]
        const ev: TranscriptEvent = {
          timestamp: new Date().toISOString(),
          speaker: speaker.trim() ? speaker.trim() : 'User',
          text: chunk,
          is_final: replayAsFinal,
        }
        props.onSend(ev)
        setReplayProgress({ index: idx + 1, total: replayChunks.length })

        const words = countWords(chunk)
        const wpm = Math.max(60, Number.isFinite(replayWpm) ? replayWpm : 155)
        const minSec = Math.max(0.2, Number.isFinite(replayMinSeconds) ? replayMinSeconds : 1.4)
        const seconds = Math.max(minSec, (words / wpm) * 60)
        const delayMs = Math.round(seconds * 1000)

        replayTimerRef.current = window.setTimeout(() => sendNext(idx + 1), delayMs)
      }

      sendNext(startIndex)
    },
    [
      props,
      replayAsFinal,
      replayChunks,
      replayMinSeconds,
      replayWpm,
      speaker,
    ],
  )

  const {
    isSupported: isMicSupported,
    status: micStatus,
    errorMessage: micErrorMessage,
    start: startMic,
    stop: stopMic,
  } = useSpeechRecognition({
    speaker,
    lang: language,
    sendInterimResults,
    onTranscriptEvent: props.onSend,
  })

  const canSend = useMemo(
    () => props.connectionState === 'open' && text.trim().length > 0,
    [props.connectionState, text],
  )

  const canUseMic = useMemo(
    () => props.connectionState === 'open' && isMicSupported,
    [isMicSupported, props.connectionState],
  )

  useEffect(() => {
    if (props.connectionState !== 'open') stopMic()
  }, [props.connectionState, stopMic])

  useEffect(() => {
    if (props.connectionState === 'open') return
    if (replayStatus === 'running' || replayStatus === 'paused') window.setTimeout(stopReplay, 0)
  }, [props.connectionState, replayStatus, stopReplay])

  useEffect(() => {
    return () => {
      if (replayTimerRef.current !== null) window.clearTimeout(replayTimerRef.current)
    }
  }, [])

  return (
    <div className="mgTranscript">
      <div className="mgPanelTitle">Transcript</div>

      <div className="mgFormRow">
        <label className="mgLabel" htmlFor="speaker">
          Speaker
        </label>
        <input
          id="speaker"
          className="mgInput"
          value={speaker}
          onChange={(e) => setSpeaker(e.target.value)}
          placeholder="User"
        />
      </div>

      <div className="mgFormRow">
        <div className="mgLabel">Live mic</div>
        {!isMicSupported ? (
          <div className="mgMuted">
            Live mic mode requires a browser with Web Speech API support (e.g. Chrome).
          </div>
        ) : (
          <>
            <div className="mgMicControls">
              <div
                className={`mgPill mgPill--${
                  micStatus === 'listening' ? 'listening' : micStatus === 'error' ? 'error' : 'idle'
                }`}
              >
                Mic: {micStatus}
              </div>
              <button
                className="mgButton mgButton--primary"
                disabled={!canUseMic || micStatus === 'listening'}
                onClick={startMic}
              >
                Start mic
              </button>
              <button className="mgButton" disabled={micStatus !== 'listening'} onClick={stopMic}>
                Stop mic
              </button>
            </div>

            {micErrorMessage ? <div className="mgErrorText">{micErrorMessage}</div> : null}

            <label className="mgCheckbox">
              <input
                type="checkbox"
                checked={sendInterimResults}
                onChange={(e) => setSendInterimResults(e.target.checked)}
              />
              <span>Send interim results</span>
            </label>

            <label className="mgLabel" htmlFor="mic-language">
              Language
            </label>
            <select
              id="mic-language"
              className="mgInput"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="en-US">English (US)</option>
              <option value="en-GB">English (UK)</option>
              <option value="de-DE">Deutsch</option>
              <option value="fr-FR">Français</option>
              <option value="es-ES">Español</option>
              <option value="it-IT">Italiano</option>
              <option value="pt-BR">Português (BR)</option>
              <option value="nl-NL">Nederlands</option>
              <option value="sv-SE">Svenska</option>
              <option value="da-DK">Dansk</option>
              <option value="no-NO">Norsk</option>
              <option value="fi-FI">Suomi</option>
              <option value="pl-PL">Polski</option>
              <option value="cs-CZ">Čeština</option>
              <option value="tr-TR">Türkçe</option>
              <option value="ja-JP">日本語</option>
              <option value="ko-KR">한국어</option>
              <option value="zh-CN">中文 (简体)</option>
              <option value="zh-TW">中文 (繁體)</option>
            </select>
          </>
        )}
      </div>

      <div className="mgFormRow">
        <label className="mgLabel" htmlFor="text">
          Text
        </label>
        <textarea
          id="text"
          className="mgTextarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a transcript event…"
          rows={5}
        />
      </div>

      <div className="mgButtonRow">
        <button
          className="mgButton mgButton--primary"
          disabled={!canSend}
          onClick={() => {
            const event: TranscriptEvent = {
              timestamp: new Date().toISOString(),
              speaker: speaker.trim() ? speaker.trim() : 'User',
              text: text.trim(),
              is_final: true,
            }
            props.onSend(event)
            setText('')
          }}
        >
          Send
        </button>
        <button
          className="mgButton"
          onClick={() => {
            props.onReset()
            setText('')
            stopReplay()
          }}
        >
          Reset
        </button>
      </div>

      <details className="mgFormRow">
        <summary className="mgLabel">Replay transcript (simulation)</summary>

        <div className="mgMuted">
          Paste a long transcript or upload a file and replay it as paced chunks (approx. real meeting speed).
        </div>

        <label className="mgLabel" htmlFor="mgReplayFile">
          Upload transcript file (txt/markdown)
        </label>
        <input
          id="mgReplayFile"
          className="mgInput"
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (!file) return
            void file.text().then((t) => {
              setReplayText(t)
              setReplayProgress({ index: 0, total: 0 })
              setReplayStatus('idle')
            })
          }}
        />

        <label className="mgLabel" htmlFor="mgReplayText">
          Full transcript
        </label>
        <textarea
          id="mgReplayText"
          className="mgTextarea"
          value={replayText}
          onChange={(e) => {
            setReplayText(e.target.value)
            setReplayProgress({ index: 0, total: 0 })
            if (replayStatus !== 'idle') stopReplay()
          }}
          placeholder="Paste a long transcript here…"
          rows={8}
        />

        <div className="mgMicControls">
          <label className="mgLabel" htmlFor="mgReplayWpm">
            WPM
          </label>
          <input
            id="mgReplayWpm"
            className="mgInput mgInput--small"
            type="number"
            min={80}
            max={240}
            value={replayWpm}
            onChange={(e) => setReplayWpm(Number.parseInt(e.target.value, 10) || 155)}
          />

          <label className="mgLabel" htmlFor="mgReplayMaxWords">
            Max words/chunk
          </label>
          <input
            id="mgReplayMaxWords"
            className="mgInput mgInput--small"
            type="number"
            min={8}
            max={80}
            value={replayMaxWords}
            onChange={(e) => setReplayMaxWords(Number.parseInt(e.target.value, 10) || 22)}
          />

          <label className="mgLabel" htmlFor="mgReplayMinSeconds">
            Min sec/chunk
          </label>
          <input
            id="mgReplayMinSeconds"
            className="mgInput mgInput--small"
            type="number"
            step="0.1"
            min={0.2}
            max={10}
            value={replayMinSeconds}
            onChange={(e) => setReplayMinSeconds(Number.parseFloat(e.target.value) || 1.4)}
          />
        </div>

        <label className="mgCheckbox">
          <input
            type="checkbox"
            checked={replayAsFinal}
            onChange={(e) => setReplayAsFinal(e.target.checked)}
          />
          <span>Send chunks as final (triggers board AI per chunk)</span>
        </label>

        <div className="mgButtonRow">
          <button
            className="mgButton mgButton--primary"
            disabled={!canReplay || replayStatus === 'running'}
            onClick={() => {
              if (!canReplay) return
              startReplayFromIndex(0)
            }}
          >
            Start replay
          </button>

          <button
            className="mgButton"
            disabled={replayStatus !== 'running'}
            onClick={() => {
              if (replayTimerRef.current !== null) window.clearTimeout(replayTimerRef.current)
              replayTimerRef.current = null
              setReplayStatus('paused')
            }}
          >
            Pause
          </button>

          <button
            className="mgButton"
            disabled={replayStatus !== 'paused'}
            onClick={() => {
              startReplayFromIndex(replayProgress.index)
            }}
          >
            Resume
          </button>

          <button className="mgButton" disabled={replayStatus === 'idle'} onClick={stopReplay}>
            Stop
          </button>
        </div>

        <div className="mgMuted">
          Status: {replayStatus}
          {replayProgress.total > 0 ? ` · ${replayProgress.index}/${replayProgress.total} chunks` : null}
        </div>
      </details>

      {props.connectionState !== 'open' ? (
        <div className="mgFormRow">
          <div className="mgMuted">Connect the backend WebSocket to send events.</div>
        </div>
      ) : null}

      <div className="mgTranscriptLog">
        {props.transcript.length === 0 ? (
          <div className="mgMuted">No transcript events yet.</div>
        ) : (
          props.transcript
            .slice()
            .reverse()
            .map((ev, idx) => (
              <div key={`${ev.timestamp}-${idx}`} className="mgTranscriptEntry">
                <div className="mgTranscriptMeta">
                  <span className="mgTranscriptSpeaker">{ev.speaker ?? 'Unknown'}</span>
                  <span className="mgTranscriptTime">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <div className="mgTranscriptText">{ev.text}</div>
              </div>
            ))
        )}
      </div>
    </div>
  )
}
