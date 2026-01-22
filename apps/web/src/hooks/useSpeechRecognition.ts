import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { TranscriptEvent } from '../contracts'

type SpeechRecognitionStatus = 'idle' | 'listening' | 'error'

type SpeechRecognitionAlternative = { transcript: string; confidence: number }
type SpeechRecognitionResult = {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternative
}
type SpeechRecognitionResultList = { length: number; [index: number]: SpeechRecognitionResult }
type SpeechRecognitionEvent = Event & { resultIndex: number; results: SpeechRecognitionResultList }
type SpeechRecognitionErrorEvent = Event & { error: string; message?: string }

type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  continuous: boolean
  maxAlternatives: number
  onstart: ((event: Event) => void) | null
  onend: ((event: Event) => void) | null
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null
}

function formatSpeechError(err: string | null): string | null {
  if (!err) return null
  if (err === 'not-allowed' || err === 'service-not-allowed') {
    return 'Microphone permission denied. Allow mic access in your browser settings and try again.'
  }
  if (err === 'no-speech') return 'No speech detected. Try speaking a bit louder or closer to the mic.'
  if (err === 'audio-capture') return 'No microphone found (or it is already in use).'
  if (err === 'network') return 'Speech recognition network error.'
  return `Speech recognition error: ${err}`
}

const INTERIM_THROTTLE_MS = 350

function createSessionId(): string {
  return `sr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function useSpeechRecognition(args: {
  speaker: string
  lang: string
  sendInterimResults: boolean
  onTranscriptEvent: (event: TranscriptEvent) => void
}): {
  isSupported: boolean
  status: SpeechRecognitionStatus
  errorMessage: string | null
  start: () => void
  stop: () => void
} {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const speakerRef = useRef(args.speaker)
  const onTranscriptEventRef = useRef(args.onTranscriptEvent)
  const langRef = useRef(args.lang)
  const sendInterimResultsRef = useRef(args.sendInterimResults)
  const sessionIdRef = useRef<string | null>(null)
  const lastInterimSentRef = useRef<Map<string, number>>(new Map())

  const [status, setStatus] = useState<SpeechRecognitionStatus>('idle')
  const [rawError, setRawError] = useState<string | null>(null)

  const isSupported = useMemo(() => getSpeechRecognitionConstructor() !== null, [])

  useEffect(() => {
    speakerRef.current = args.speaker
  }, [args.speaker])

  useEffect(() => {
    onTranscriptEventRef.current = args.onTranscriptEvent
  }, [args.onTranscriptEvent])

  useEffect(() => {
    langRef.current = args.lang
    if (recognitionRef.current) recognitionRef.current.lang = args.lang
  }, [args.lang])

  useEffect(() => {
    sendInterimResultsRef.current = args.sendInterimResults
    if (recognitionRef.current) recognitionRef.current.interimResults = args.sendInterimResults
  }, [args.sendInterimResults])

  const stop = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) {
      setStatus('idle')
      return
    }

    try {
      recognition.stop()
    } catch {
      // ignore
    } finally {
      setStatus('idle')
    }
  }, [])

  const start = useCallback(() => {
    const SpeechRecognitionCtor = getSpeechRecognitionConstructor()
    if (!SpeechRecognitionCtor) {
      setRawError('unsupported')
      setStatus('error')
      return
    }

    if (!recognitionRef.current) {
      const recognition = new SpeechRecognitionCtor()
      recognitionRef.current = recognition
      recognition.continuous = true
      recognition.maxAlternatives = 1

      recognition.onstart = () => {
        setRawError(null)
        setStatus('listening')
      }

      recognition.onend = () => {
        setStatus((prev) => (prev === 'error' ? prev : 'idle'))
      }

      recognition.onerror = (event) => {
        setRawError(event?.error ?? 'unknown')
        setStatus('error')
      }

      recognition.onresult = (event) => {
        const speaker = speakerRef.current.trim() ? speakerRef.current.trim() : 'User'
        const allowInterim = sendInterimResultsRef.current
        const sessionId = sessionIdRef.current ?? createSessionId()
        sessionIdRef.current = sessionId
        const now = Date.now()

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i]
          const alternative = result?.[0]
          const text = String(alternative?.transcript ?? '').trim()
          if (!text) continue

          const isFinal = Boolean(result?.isFinal)
          if (!isFinal && !allowInterim) continue
          const eventId = `${sessionId}:${i}`

          if (!isFinal) {
            const lastSentAt = lastInterimSentRef.current.get(eventId) ?? 0
            if (now - lastSentAt < INTERIM_THROTTLE_MS) continue
            lastInterimSentRef.current.set(eventId, now)
          } else {
            lastInterimSentRef.current.delete(eventId)
          }

          const confidence =
            typeof alternative?.confidence === 'number' && Number.isFinite(alternative.confidence)
              ? alternative.confidence
              : undefined

          onTranscriptEventRef.current({
            timestamp: new Date().toISOString(),
            event_id: eventId,
            speaker,
            text,
            confidence,
            is_final: isFinal,
          })
        }
      }
    }

    const recognition = recognitionRef.current
    if (!recognition) return

    setRawError(null)
    recognition.lang = langRef.current
    recognition.interimResults = sendInterimResultsRef.current
    sessionIdRef.current = createSessionId()
    lastInterimSentRef.current.clear()

    try {
      recognition.start()
      setStatus('listening')
    } catch (err) {
      setRawError(err instanceof Error ? err.message : 'failed-to-start')
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    return () => {
      const recognition = recognitionRef.current
      if (!recognition) return
      recognition.onstart = null
      recognition.onend = null
      recognition.onresult = null
      recognition.onerror = null
      try {
        recognition.abort()
      } catch {
        // ignore
      }
    }
  }, [])

  const errorMessage = useMemo(() => {
    if (rawError === 'unsupported') return 'Live mic mode is not supported in this browser.'
    if (rawError?.includes('not allowed')) return formatSpeechError('not-allowed')
    return formatSpeechError(rawError)
  }, [rawError])

  return useMemo(
    () => ({ isSupported, status, errorMessage, start, stop }),
    [errorMessage, isSupported, start, status, stop],
  )
}
