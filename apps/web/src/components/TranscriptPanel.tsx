import { useEffect, useMemo, useState } from 'react'
import type { TranscriptEvent } from '../contracts'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'

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
          }}
        >
          Reset
        </button>
      </div>

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
