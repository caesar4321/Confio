// Realtime voice calls with Confio Assistant (Assistant+), over WebRTC straight to OpenAI.
//
// The server mints a short-lived client secret and owns every tool that
// touches the user's data: when the model calls one, we relay it to
// runAssistantVoiceTool and hand the server's answer back. `navigate` is the
// only tool the app runs itself. Transcripts and a heartbeat go to the server
// every few seconds; the server measures minutes from its own clock and tells
// us to hang up when the month's minutes run out.
import { NativeModules } from 'react-native';
import type { ApolloClient } from '@apollo/client';
import { RTCPeerConnection, mediaDevices, type MediaStream } from 'react-native-webrtc';
import {
  CONNECT_ASSISTANT_VOICE,
  LOG_ASSISTANT_VOICE,
  RUN_ASSISTANT_VOICE_TOOL,
  START_ASSISTANT_VOICE,
} from './api';
import { openDestination } from './destinations';

const FLUSH_MS = 8000;

export type CallState = 'connecting' | 'listening' | 'thinking' | 'speaking' | 'ended';
export type Caption = { role: 'user' | 'assistant'; text: string };

type Callbacks = {
  onState: (state: CallState) => void;
  onCaption: (caption: Caption) => void;
  onEnded: (reason?: string) => void;
  onMinutesLeft?: (minutes: number) => void;
  onNavigate?: () => void;
};

export class VoiceCall {
  private pc: RTCPeerConnection | null = null;
  private channel: any = null;
  private stream: MediaStream | null = null;
  private sessionId: string | null = null;
  private pendingTranscript: Caption[] = [];
  private pendingUsage: object[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private ended = false;
  private muted = false;

  constructor(
    private client: ApolloClient<any>,
    private cb: Callbacks,
    private opts: { screen?: string; timezone?: string; isBusiness?: boolean } = {},
  ) {}

  async start() {
    this.cb.onState('connecting');
    let start: any;
    try {
      const { data } = await this.client.mutate({
        mutation: START_ASSISTANT_VOICE,
        variables: { screen: this.opts.screen ?? null, timezone: this.opts.timezone ?? null },
      });
      start = data?.startAssistantVoice;
    } catch {
      this.finish('No pudimos iniciar la llamada. Revisa tu conexión.');
      return;
    }
    if (this.ended) {
      return; // hung up while the session was being created
    }
    if (!start?.success || !start.sessionId) {
      this.finish(start?.error || 'No pudimos iniciar la llamada.');
      return;
    }
    this.sessionId = start.sessionId;
    this.cb.onMinutesLeft?.(start.minutesLeft);

    try {
      const stream = await mediaDevices.getUserMedia({ audio: true, video: false });
      if (this.ended) {
        // Hung up while the mic permission/prompt was open: release it now.
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      // A mute pressed while the mic was being acquired still applies.
      stream.getAudioTracks().forEach((t) => {
        t.enabled = !this.muted;
      });
      this.stream = stream;
      const pc = new RTCPeerConnection({});
      this.pc = pc;
      this.stream.getTracks().forEach((track) => pc.addTrack(track, this.stream!));
      (pc as any).addEventListener('track', () => {
        // Remote audio plays by itself; send it to the loudspeaker.
        NativeModules.ConfioAudioRoute?.setSpeaker(true).catch(() => {});
      });
      (pc as any).addEventListener('connectionstatechange', () => {
        if (['failed', 'closed'].includes((pc as any).connectionState) && !this.ended) {
          this.finish('Se cortó la llamada.');
        }
      });

      const channel = pc.createDataChannel('oai-events');
      this.channel = channel;
      (channel as any).addEventListener('message', (event: { data: string }) => this.onEvent(event.data));

      const offer = await pc.createOffer({});
      await pc.setLocalDescription(offer);
      if (this.ended) {
        this.release();
        return;
      }
      // The server does the handshake with OpenAI: it holds the session
      // secret and records the call id, so it can always hang up.
      const { data: connected } = await this.client.mutate({
        mutation: CONNECT_ASSISTANT_VOICE,
        variables: { sessionId: this.sessionId, offerSdp: offer.sdp },
      });
      const connect = connected?.connectAssistantVoice;
      if (!connect?.success || !connect.answerSdp) {
        throw new Error(connect?.error || 'connect failed');
      }
      const answer = connect.answerSdp;
      if (this.ended) {
        this.release();
        return;
      }
      await pc.setRemoteDescription({ type: 'answer', sdp: answer } as any);
      if (this.ended) {
        this.release();
        return;
      }
      this.cb.onState('listening');
      void this.flush();
      this.flushTimer = setInterval(() => void this.flush(), FLUSH_MS);
    } catch (e) {
      if (!this.ended) {
        this.finish('No pudimos conectar la llamada. Revisa tu conexión.');
      } else {
        this.release();
      }
    }
  }

  setMuted(muted: boolean) {
    this.muted = muted;
    this.stream?.getAudioTracks().forEach((t) => {
      t.enabled = !muted;
    });
  }

  get isMuted() {
    return this.muted;
  }

  hangUp() {
    this.finish();
  }

  private send(event: object) {
    try {
      this.channel?.send(JSON.stringify(event));
    } catch {
      // channel closing
    }
  }

  private onEvent(raw: string) {
    let event: any;
    try {
      event = JSON.parse(raw);
    } catch {
      return;
    }
    switch (event.type) {
      case 'input_audio_buffer.speech_started':
        this.cb.onState('listening');
        break;
      case 'input_audio_buffer.speech_stopped':
        this.cb.onState('thinking');
        break;
      case 'output_audio_buffer.started':
        this.cb.onState('speaking');
        break;
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared':
        this.cb.onState('listening');
        break;
      case 'conversation.item.input_audio_transcription.completed':
        this.caption({ role: 'user', text: event.transcript });
        break;
      case 'response.output_audio_transcript.done':
        this.caption({ role: 'assistant', text: event.transcript });
        break;
      case 'response.function_call_arguments.done':
        void this.runTool(event.name, event.call_id, event.arguments);
        break;
      case 'response.done':
        if (event.response?.usage) {
          this.pendingUsage.push(event.response.usage);
        }
        break;
      case 'error':
        // Recoverable protocol errors arrive here; a dead call shows up as a
        // connection state change instead.
        break;
    }
  }

  private caption(caption: Caption) {
    const text = (caption.text || '').trim();
    if (!text) {
      return;
    }
    this.pendingTranscript.push({ ...caption, text });
    this.cb.onCaption({ ...caption, text });
  }

  private async runTool(name: string, callId: string, args: string) {
    let output: string;
    if (name === 'navigate') {
      let destination = '';
      try {
        destination = JSON.parse(args || '{}').destination;
      } catch {
        destination = '';
      }
      const ok = openDestination(destination, { isBusiness: this.opts.isBusiness });
      if (ok) {
        this.cb.onNavigate?.();
      }
      output = JSON.stringify({ ok });
    } else if (this.sessionId) {
      try {
        const { data } = await this.client.mutate({
          mutation: RUN_ASSISTANT_VOICE_TOOL,
          variables: { sessionId: this.sessionId, name, arguments: args },
        });
        const tool = data?.runAssistantVoiceTool;
        output = tool?.output ?? '{"error": "sin respuesta"}';
        if (tool && tool.keepGoing === false) {
          this.finish('La llamada terminó.');
          return;
        }
      } catch {
        output = '{"error": "No pude consultarlo ahora."}';
      }
    } else {
      output = '{"error": "llamada no iniciada"}';
    }
    this.send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output } });
    this.send({ type: 'response.create' });
  }

  private async flush(ended = false) {
    if (!this.sessionId) {
      return;
    }
    const transcript = this.pendingTranscript.splice(0);
    const usage = this.pendingUsage.splice(0);
    const merged = usage.reduce<Record<string, any>>((acc, u: any) => {
      for (const side of ['input_token_details', 'output_token_details']) {
        acc[side] = acc[side] || {};
        for (const [k, v] of Object.entries(u?.[side] || {})) {
          if (typeof v === 'number') {
            acc[side][k] = (acc[side][k] || 0) + v;
          }
        }
      }
      return acc;
    }, {});
    try {
      const { data } = await this.client.mutate({
        mutation: LOG_ASSISTANT_VOICE,
        variables: {
          sessionId: this.sessionId,
          transcript,
          usageJson: usage.length ? JSON.stringify(merged) : null,
          ended,
        },
      });
      const log = data?.logAssistantVoice;
      if (log) {
        this.cb.onMinutesLeft?.(log.minutesLeft);
        if (!log.keepGoing && !ended) {
          this.finish('Usaste tus minutos de voz de este mes. Puedes seguir por texto.');
        }
      }
    } catch {
      // Put the transcript back; it goes with the next heartbeat.
      this.pendingTranscript.unshift(...transcript);
    }
  }

  // Close everything this call holds; safe to call more than once.
  private release() {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    try {
      this.channel?.close();
    } catch {}
    try {
      this.pc?.close();
    } catch {}
    this.stream?.getTracks().forEach((t) => t.stop());
    this.channel = null;
    this.pc = null;
    this.stream = null;
    NativeModules.ConfioAudioRoute?.setSpeaker(false).catch(() => {});
  }

  private finish(reason?: string) {
    if (this.ended) {
      return;
    }
    this.ended = true;
    void this.flush(true);
    this.release();
    this.cb.onState('ended');
    this.cb.onEnded(reason);
  }
}
