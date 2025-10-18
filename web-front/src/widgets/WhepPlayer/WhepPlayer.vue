<template>
  <div class="whep">
    <video ref="videoEl" class="video" playsinline :muted="muted" :autoplay="autoplay" />
    <div v-if="errorMsg" class="overlay error">{{ errorMsg }}</div>
    <div v-if="!connected && !errorMsg" class="overlay hint">{{ hintText }}</div>
    <div class="controls">
      <slot name="right"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

type PC = RTCPeerConnection

const props = withDefaults(defineProps<{ whepUrl?: string; autoplay?: boolean; token?: string; muted?: boolean }>(), {
  whepUrl: '',
  autoplay: true,
  token: '',
  muted: true
})

const videoEl = ref<HTMLVideoElement | null>(null)
const pcRef = ref<PC | null>(null)
const resourceUrl = ref<string>('')
const pendingCandidates = ref<string[]>([])
const connected = ref(false)
const errorMsg = ref('')
const stopping = ref(false)
let reconnectAttempts = 0
let reconnectTimer: number | null = null
let statsTimer: number | null = null
let lastRvfcLog = 0

const hintText = computed(() => (props.whepUrl ? 'Connecting...' : 'No source selected'))

function clearTimers() {
  if (reconnectTimer) { window.clearTimeout(reconnectTimer); reconnectTimer = null }
  if (statsTimer) { window.clearInterval(statsTimer); statsTimer = null }
}

async function stopSession() {
  stopping.value = true
  try {
    clearTimers()
    if (resourceUrl.value) {
      try { await fetch(resourceUrl.value, { method: 'DELETE', mode: 'cors' }) } catch {}
      resourceUrl.value = ''
    }
    const pc = pcRef.value
    if (pc) {
      try { pc.getTransceivers().forEach(t => { try { (t as any).stop && (t as any).stop() } catch {} }) } catch {}
      try { pc.getSenders().forEach(s => { try { s.track && s.track.stop() } catch {} }) } catch {}
      try { pc.close() } catch {}
    }
  } finally {
    pcRef.value = null
    connected.value = false
    stopping.value = false
  }
}

async function startSession(url: string) {
  errorMsg.value = ''
  connected.value = false

  let STUN_URL = 'stun:stun.l.google.com:19302'
  try {
    const envAny: any = (import.meta as any)
    if (envAny && envAny.env && typeof envAny.env.VITE_STUN_URL === 'string' && envAny.env.VITE_STUN_URL.length > 0) {
      STUN_URL = String(envAny.env.VITE_STUN_URL)
    }
  } catch {}

  const pc = new RTCPeerConnection({
    sdpSemantics: 'unified-plan',
    iceServers: [{ urls: STUN_URL }]
  } as any)
  pcRef.value = pc

  console.log('[WHEP] startSession url=', url)

  try {
    const tr = pc.addTransceiver('video', { direction: 'recvonly' })
    // Prefer H.264 first to align with server encoder and avoid VP8
    try {
      const caps: any = (window as any).RTCRtpReceiver?.getCapabilities?.('video')
      const all = (caps && Array.isArray(caps.codecs)) ? caps.codecs : []
      const h264 = all.filter((c: any) => String(c.mimeType || '').toLowerCase() === 'video/h264')
      const others = all.filter((c: any) => String(c.mimeType || '').toLowerCase() !== 'video/h264')
      if ((tr as any).setCodecPreferences && h264.length) {
        ;(tr as any).setCodecPreferences([...h264, ...others])
        console.log('[WHEP] codec prefs set to H264-first, count=', h264.length)
      }
    } catch {}
    if (!props.muted) pc.addTransceiver('audio', { direction: 'recvonly' })

    pc.ontrack = (ev: RTCTrackEvent) => {
      const v = videoEl.value
      if (!v || !ev.streams || !ev.streams[0]) return
      v.srcObject = ev.streams[0]

      try {
        ev.track.onunmute = () => console.log('[WHEP] track onunmute kind=', ev.track.kind)
        ev.track.onmute = () => console.log('[WHEP] track mute kind=', ev.track.kind)
      } catch {}

      v.addEventListener('loadedmetadata', () => console.log('[WHEP] video loadedmetadata', v.videoWidth + 'x' + v.videoHeight))
      v.addEventListener('playing', () => console.log('[WHEP] video playing'))
      v.addEventListener('waiting', () => console.log('[WHEP] video waiting'))
      v.addEventListener('pause', () => console.log('[WHEP] video pause'))
      v.addEventListener('error', () => console.log('[WHEP] video error'))

      const vv: any = v
      if (vv && typeof vv.requestVideoFrameCallback === 'function') {
        const rvfc = (now: number, meta: any) => {
          if (now - lastRvfcLog > 1000) {
            console.log('[WHEP] rVFC presentedFrames=', (meta && meta.presentedFrames), 'size=', v.videoWidth + 'x' + v.videoHeight)
            lastRvfcLog = now
          }
          vv.requestVideoFrameCallback(rvfc)
        }
        vv.requestVideoFrameCallback(rvfc)
      } else {
        console.log('[WHEP] rVFC not supported')
      }

      const pr: any = vv && vv.play && vv.play()
      if (pr && pr.then) {
        pr.catch((e: any) => {
          console.warn('[WHEP] play blocked', e)
          if (!props.muted) errorMsg.value = 'Autoplay blocked, mute or click play'
        })
      }

      if (statsTimer) window.clearInterval(statsTimer)
      statsTimer = window.setInterval(async () => {
        try {
          const pcNow: any = pcRef.value
          if (!pcNow || !pcNow.getStats) return
          const rep = await pcNow.getStats()
          let printed = false
          rep.forEach((r: any) => {
            if (r.type === 'inbound-rtp' && (r.kind === 'video' || r.mediaType === 'video')) {
              console.log('[WHEP] stats inbound-rtp', 'fps=', r.framesPerSecond, 'decoded=', r.framesDecoded, 'bytes=', r.bytesReceived, 'pkts=', r.packetsReceived, 'jitter=', r.jitter)
              printed = true
            } else if (r.type === 'track' && (r.kind === 'video' || r.mediaType === 'video')) {
              console.log('[WHEP] stats track', 'decoded=', r.framesDecoded, 'received=', r.framesReceived, 'dropped=', r.framesDropped)
              printed = true
            }
          })
          if (!printed) console.log('[WHEP] stats: no inbound-rtp/track yet')
        } catch {}
      }, 2000)
    }

    pc.onicecandidate = async (ev) => {
      if (!ev.candidate) return
      const cand = ev.candidate.candidate
      const mid = ev.candidate.sdpMid || 'video'
      const frag = 'a=candidate:' + cand + '\r\n' + 'a=mid:' + mid + '\r\n'
      try {
        const fragHead = frag.substring(0, 180).replace(/\r|\n/g, ' ')
        console.log('[WHEP] patch_frag_head', fragHead)
      } catch {}
      if (resourceUrl.value) {
        try {
          const hdrs: Record<string,string> = { 'Content-Type': 'application/trickle-ice-sdpfrag' }
          if (props.token) hdrs['Authorization'] = 'Bearer ' + props.token
          await fetch(resourceUrl.value, { method: 'PATCH', mode: 'cors', headers: hdrs, body: frag })
          console.log('[WHEP] PATCH candidate ok')
        } catch (err) {
          console.warn('[WHEP] PATCH candidate failed', err)
        }
      } else {
        pendingCandidates.value.push(frag)
      }
    }

    pc.onconnectionstatechange = () => {
      console.log('[WHEP] pc.state=', pc.connectionState)
      if (pc.connectionState === 'connected') { connected.value = true; reconnectAttempts = 0 }
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed' || pc.connectionState === 'disconnected') {
        connected.value = false
        if (props.autoplay && !stopping.value && props.whepUrl) {
          if (reconnectTimer) window.clearTimeout(reconnectTimer)
          const delay = Math.min(10000, 800 * Math.pow(2, reconnectAttempts++))
          console.warn('[WHEP] reconnect scheduled in', delay, 'ms')
          reconnectTimer = window.setTimeout(async () => { try { await stopSession(); await ensureStart() } catch {} }, delay)
        }
      }
    }

    pc.oniceconnectionstatechange = () => {
      const iceState: any = (pc as any).iceConnectionState
      console.log('[WHEP] ice.state=', iceState)
      if ((iceState === 'failed' || iceState === 'disconnected') && props.autoplay && !stopping.value && props.whepUrl) {
        if (reconnectTimer) window.clearTimeout(reconnectTimer)
        const delay = Math.min(10000, 800 * Math.pow(2, reconnectAttempts++))
        console.warn('[WHEP] ice reconnect scheduled in', delay, 'ms')
        reconnectTimer = window.setTimeout(async () => { try { await stopSession(); await ensureStart() } catch {} }, delay)
      }
    }

    const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: !props.muted } as any)
    await pc.setLocalDescription(offer)
    console.log('[WHEP] setLocalDescription ok, offer_len=', (offer && offer.sdp ? offer.sdp.length : 0))

    await new Promise<void>((resolve) => {
      let done = false
      const timer = window.setTimeout(() => { if (!done) { done = true; resolve() } }, 1500)
      pc.onicegatheringstatechange = () => {
        if (!done && pc.iceGatheringState === 'complete') { done = true; window.clearTimeout(timer); console.log('[WHEP] ICE gathering complete'); resolve() }
      }
    })

    // Log negotiated transceivers directions for debugging
    try {
      setTimeout(() => {
        (pc.getTransceivers?.() || []).forEach((t: any, idx: number) => {
          console.log('[WHEP] tr', idx, 'dir=', t?.direction, 'current=', t?.currentDirection)
        })
      }, 0)
    } catch {}

    // 标准做法：POST 初始 Offer（m-line 端口应为 9），后续候选用 PATCH trickle
    const sdp = offer && offer.sdp ? offer.sdp : ((pc.localDescription && pc.localDescription.sdp) ? pc.localDescription.sdp : '')
    try {
      const offerHead = sdp.substring(0, 200).replace(/\r|\n/g, ' ')
      console.log('[WHEP] offer_sdp_head', offerHead)
    } catch {}
    const headers: Record<string,string> = { 'Content-Type': 'application/sdp' }
    if (props.token) headers['Authorization'] = 'Bearer ' + props.token
    const resp = await fetch(url, { method: 'POST', mode: 'cors', headers, body: sdp })
    console.log('[WHEP] POST /whep status=', resp.status)
    if (!resp.ok) throw new Error('WHEP POST failed: ' + resp.status)
    const answer = await resp.text()
    const loc = resp.headers.get('Location') || ''
    resourceUrl.value = loc ? (new URL(loc, url)).toString() : ''
    if (!resourceUrl.value) console.log('[WHEP] Location header missing')
    console.log('[WHEP] Answer len=', answer.length, 'resource=', resourceUrl.value)
    try {
      const ansHead = answer.substring(0, 200).replace(/\r|\n/g, ' ')
      console.log('[WHEP] answer_sdp_head', ansHead)
    } catch {}
    await pc.setRemoteDescription({ type: 'answer', sdp: answer } as any)
    console.log('[WHEP] setRemoteDescription ok')

    if (pendingCandidates.value.length && resourceUrl.value) {
      for (const frag of pendingCandidates.value) {
        try {
          const hdrs2: Record<string,string> = { 'Content-Type': 'application/trickle-ice-sdpfrag' }
          if (props.token) hdrs2['Authorization'] = 'Bearer ' + props.token
          await fetch(resourceUrl.value, { method: 'PATCH', mode: 'cors', headers: hdrs2, body: frag })
        } catch {}
      }
      pendingCandidates.value = []
    }

    // Signal end-of-candidates to close gathering on server side (WHEP sdpfrag)
    try {
      if (resourceUrl.value) {
        const hdrs: Record<string,string> = { 'Content-Type': 'application/trickle-ice-sdpfrag' }
        if (props.token) hdrs['Authorization'] = 'Bearer ' + props.token
        const mid = '0'
        const eof = 'a=end-of-candidates\r\n' + 'a=mid:' + mid + '\r\n'
        await fetch(resourceUrl.value, { method: 'PATCH', mode: 'cors', headers: hdrs, body: eof })
        console.log('[WHEP] PATCH end-of-candidates sent')
      }
    } catch {}
  } catch (e: any) {
    errorMsg.value = (e && e.message) ? e.message : 'WHEP failed'
    await stopSession()
    throw e
  }
}

let retry = 0
async function ensureStart() {
  if (!props.autoplay || !props.whepUrl) return
  try {
    await startSession(props.whepUrl)
    retry = 0
    reconnectAttempts = 0
  } catch {
    const delay = Math.min(16000, 1000 * Math.pow(2, retry++))
    console.warn('[WHEP] start retry #', retry, 'delay=', delay)
    if (retry <= 5) window.setTimeout(() => { if (props.whepUrl) ensureStart() }, delay)
  }
}

watch(() => props.whepUrl, async (val, old) => { if (val === old) return; await stopSession(); if (props.autoplay && val) ensureStart() })
async function refresh() { await stopSession(); if (props.autoplay && props.whepUrl) ensureStart() }
defineExpose({ refresh })
onBeforeUnmount(() => { stopSession() })
if (props.autoplay && props.whepUrl) ensureStart()
</script>

<style scoped>
.whep{ position:relative; width:100%; padding-top:56.25%; background:#05070e; border-radius:10px; overflow:hidden; }
.video{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#000; }
.overlay{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#9dbad9; font-size:14px; pointer-events:none; }
.overlay.hint{ color:#7aa0c7; }
.overlay.error{ color:#ff7777; }
.controls{ position:absolute; right:12px; bottom:12px; display:flex; gap:8px; z-index:2; }
</style>
