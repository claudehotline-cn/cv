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
const diagEnabled = (() => { try { return String(((import.meta as any).env?.VITE_WHEP_DEBUG ?? '')).trim() === '1' } catch { return false } })()
let lastRvfcLog = 0
let flowGuardTimer: number | null = null

const hintText = computed(() => (props.whepUrl ? 'Connecting...' : 'No source selected'))

function clearTimers() {
  if (reconnectTimer) { window.clearTimeout(reconnectTimer); reconnectTimer = null }
  if (statsTimer) { window.clearInterval(statsTimer); statsTimer = null }
  if (flowGuardTimer) { window.clearTimeout(flowGuardTimer); flowGuardTimer = null }
}

async function stopSession() {
  stopping.value = true
  try {
    clearTimers()
    if (resourceUrl.value) {
      try { await fetch(resourceUrl.value, { method: 'DELETE', mode: 'cors', keepalive: true as any }) } catch {}
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

  // ICE 服务器：优先从 VITE_ICE_SERVERS 读取；为空则使用公共 STUN
  let iceServers: RTCIceServer[] = []
  try {
    const envVal = ((import.meta as any).env?.VITE_ICE_SERVERS || '').toString().trim()
    if (envVal) {
      if (envVal.startsWith('[')) {
        iceServers = JSON.parse(envVal)
      } else {
        iceServers = envVal.split(',').map((u: string) => ({ urls: u.trim() })).filter((x: any) => !!x.urls)
      }
    }
  } catch {}
  if (!iceServers.length) iceServers = [{ urls: 'stun:stun.l.google.com:19302' }]
  const pc = new RTCPeerConnection({
    sdpSemantics: 'unified-plan',
    // 使用 env/默认 STUN
    iceServers
  } as any)
  pcRef.value = pc
  try { (window as any).__pcLast = pc; (window as any).pc = pc } catch {}

  console.log('[WHEP] startSession url=', url)

  try {
    let videoMid = '0'
    const tr = pc.addTransceiver('video', { direction: 'recvonly' })
    // Prefer H.264 packetization-mode=1 strictly, then other H.264, then others
    try {
      const caps: any = (window as any).RTCRtpReceiver?.getCapabilities?.('video')
      const all = (caps && Array.isArray(caps.codecs)) ? caps.codecs : []
      const h264 = all.filter((c: any) => String(c.mimeType || '').toLowerCase() === 'video/h264')
      const h264_p1 = h264.filter((c: any) => /packetization-mode=1/i.test(String(c.sdpFmtpLine||'')))
      const h264_rest = h264.filter((c: any) => !/packetization-mode=1/i.test(String(c.sdpFmtpLine||'')))
      const others = all.filter((c: any) => String(c.mimeType || '').toLowerCase() !== 'video/h264')
      if ((tr as any).setCodecPreferences && h264.length) {
        const order = [...(h264_p1.length?h264_p1:h264), ...h264_rest, ...others]
        ;(tr as any).setCodecPreferences(order)
        console.log('[WHEP] codec prefs set to H264(pmode1)-first, p1=', h264_p1.length, 'h264=', h264.length)
      }
    } catch {}
    if (!props.muted) pc.addTransceiver('audio', { direction: 'recvonly' })

    pc.ontrack = (ev: RTCTrackEvent) => {
      const v = videoEl.value
      if (!v) return
      const stream = (ev.streams && ev.streams[0]) ? ev.streams[0] : new MediaStream([ev.track])
      v.srcObject = stream

      try {
        ev.track.onunmute = () => console.log('[WHEP] track onunmute kind=', ev.track.kind)
        ev.track.onmute = () => console.log('[WHEP] track mute kind=', ev.track.kind)
      } catch {}

      v.addEventListener('loadedmetadata', async () => {
        console.log('[WHEP] video loadedmetadata', v.videoWidth + 'x' + v.videoHeight)
        try { await v.play() } catch (e) { console.warn('[WHEP] play() after loadedmetadata failed', (e as any)?.message || e) }
      })
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

      // stats 定位：优先使用接收端 receiver.getStats() 聚焦视频收流
      if (statsTimer) window.clearInterval(statsTimer)
      statsTimer = window.setInterval(async () => {
        try {
          const pcNow: any = pcRef.value
          if (!pcNow) return
          const rx = (pcNow.getReceivers?.() || []).find((r: any) => r.track?.kind === 'video')
          if (!rx || !rx.getStats) return
          const rep = await rx.getStats()
          let logged = false
          rep.forEach((s: any) => {
            if (s.type === 'inbound-rtp') {
              console.log('[WHEP] inbound-rtp bytes=', s.bytesReceived, 'pkts=', s.packetsReceived, 'fps=', s.framesPerSecond, 'decoded=', s.framesDecoded)
              logged = true
            } else if (s.type === 'track') {
              console.log('[WHEP] track stats decoded=', s.framesDecoded, 'received=', s.framesReceived, 'dropped=', s.framesDropped)
              logged = true
            }
          })
          if (!logged) console.log('[WHEP] receiver stats: no inbound-rtp yet')
        } catch {}
      }, 2000)
    }

    pc.onicecandidate = async (ev) => {
      if (!ev.candidate) return
      const cand = ev.candidate.candidate
      // 后端以 offer 中的第一个 m=video 的 a=mid 对齐，现代浏览器一般为 '0'
      // 为避免不兼容，将回退从 'video' 改为 '0'
      const mid = ev.candidate.sdpMid || videoMid || '0'
      // 注意：ev.candidate.candidate 本身已含有 "candidate:" 前缀，这里不要重复添加
      const frag = 'a=' + cand + '\r\n' + 'a=mid:' + mid + '\r\n'
      // 附带 ice-ufrag，增强服务端 sdpfrag 关联健壮性
      const __ufrag = (() => { try { const m = (pc.localDescription?.sdp||'').match(/^a=ice-ufrag:(.+)$/m); return (m && m[1])? m[1].trim(): '' } catch { return '' } })()
      const __pwd   = (() => { try { const m = (pc.localDescription?.sdp||'').match(/^a=ice-pwd:(.+)$/m);   return (m && m[1])? m[1].trim(): '' } catch { return '' } })()
      const frag2 = frag + (__ufrag ? ('a=ice-ufrag:' + __ufrag + '\r\n') : '') + (__pwd ? ('a=ice-pwd:' + __pwd + '\r\n') : '')
      try {
        const fragHead = frag.substring(0, 180).replace(/\r|\n/g, ' ')
        console.log('[WHEP] patch_frag_head', fragHead)
      } catch {}
      if (resourceUrl.value) {
        try {
          const hdrs: Record<string,string> = { 'Content-Type': 'application/trickle-ice-sdpfrag' }
          if (props.token) hdrs['Authorization'] = 'Bearer ' + props.token
          await fetch(resourceUrl.value, { method: 'PATCH', mode: 'cors', headers: hdrs, body: frag2 })
          console.log('[WHEP] PATCH candidate ok')
        } catch (err) {
          console.warn('[WHEP] PATCH candidate failed', err)
        }
      } else {
        pendingCandidates.value.push(frag2)
      }
    }

    pc.onconnectionstatechange = () => {
      console.log('[WHEP] pc.state=', pc.connectionState)
      if (pc.connectionState === 'connected') { connected.value = true; reconnectAttempts = 0; try { const v = videoEl.value; if (v) v.play().catch(()=>{}) } catch {} }
      // 仅在 failed/closed 时重连；disconnected 可能为瞬时抖动，先观察不立刻重建
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
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
      // 与 connectionState 策略保持一致：只在 failed 时介入，避免 disconnected 抖动引发重连风暴
      if ((iceState === 'failed') && props.autoplay && !stopping.value && props.whepUrl) {
        if (reconnectTimer) window.clearTimeout(reconnectTimer)
        const delay = Math.min(10000, 800 * Math.pow(2, reconnectAttempts++))
        console.warn('[WHEP] ice reconnect scheduled in', delay, 'ms')
        reconnectTimer = window.setTimeout(async () => { try { await stopSession(); await ensureStart() } catch {} }, delay)
      }
    }

    const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: !props.muted } as any)
    await pc.setLocalDescription(offer)
    console.log('[WHEP] setLocalDescription ok, offer_len=', (offer && offer.sdp ? offer.sdp.length : 0))
    try { const tr0: any = pc.getTransceivers?.()[0]; if (tr0?.mid) videoMid = tr0.mid } catch {}

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
    try { const v = videoEl.value; if (v) await v.play().catch(()=>{}) } catch {}

    // 额外：打印实际选中的编解码器，便于核对 fmtp/pt
    try {
      setTimeout(() => {
        const tr0: any = pc.getTransceivers?.()[0]
        console.log('[WHEP] selected codecs =', tr0?.receiver?.getParameters?.().codecs)
      }, 800)
    } catch {}

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
        const mid = videoMid || '0'
        const eof = 'a=end-of-candidates\r\n' + 'a=mid:' + mid + '\r\n'
        const __ufrag2 = (() => { try { const m = (pc.localDescription?.sdp||'').match(/^a=ice-ufrag:(.+)$/m); return (m && m[1])? m[1].trim(): '' } catch { return '' } })()
        const __pwd2   = (() => { try { const m = (pc.localDescription?.sdp||'').match(/^a=ice-pwd:(.+)$/m);   return (m && m[1])? m[1].trim(): '' } catch { return '' } })()
        const eof2 = eof + (__ufrag2 ? ('a=ice-ufrag:' + __ufrag2 + '\r\n') : '') + (__pwd2 ? ('a=ice-pwd:' + __pwd2 + '\r\n') : '')
        await fetch(resourceUrl.value, { method: 'PATCH', mode: 'cors', headers: hdrs, body: eof2 })
        console.log('[WHEP] PATCH end-of-candidates sent')
      }
    } catch {}

    // 若较长时间仍无 inbound-rtp，自动重建连接（延长守护窗口，避免误判）
    try {
      if (flowGuardTimer) { window.clearTimeout(flowGuardTimer); flowGuardTimer = null }
      if (diagEnabled) {
        flowGuardTimer = window.setTimeout(async () => {
          try {
            const pcNow: any = pcRef.value
            if (!pcNow) return
            const rx = (pcNow.getReceivers?.() || []).find((r: any) => r.track?.kind === 'video')
            if (!rx || !rx.getStats) return
            const rep = await rx.getStats()
            let ok = false
            rep.forEach((s: any) => { if (s.type === 'inbound-rtp' && (((s.bytesReceived||0) > 0) || ((s.framesDecoded||0) > 0))) ok = true })
            if (!ok) {
              console.warn('[WHEP] no inbound after guard window, restarting')
              try { (window as any).__whepDiag = { reason: 'no_inbound_guard', ts: Date.now(), url } } catch {}
              await stopSession(); await ensureStart()
            }
          } catch {}
        }, 20000)
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

// 在页面刷新/关闭时尝试优雅关闭会话（尽力而为）
try {
  const onUnload = () => {
    try { clearTimers() } catch {}
    const url = resourceUrl.value
    if (url) {
      try { navigator.sendBeacon && navigator.sendBeacon(url, new Blob([], { type: 'text/plain' })) } catch {}
      try { fetch(url, { method: 'DELETE', mode: 'cors', keepalive: true as any }).catch(()=>{}) } catch {}
    }
    try { const pc = pcRef.value; if (pc) pc.close() } catch {}
  }
  window.addEventListener('beforeunload', onUnload)
} catch {}
</script>

<style scoped>
.whep{ position:relative; width:100%; padding-top:56.25%; background:#05070e; border-radius:10px; overflow:hidden; }
.video{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#000; }
.overlay{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#9dbad9; font-size:14px; pointer-events:none; }
.overlay.hint{ color:#7aa0c7; }
.overlay.error{ color:#ff7777; }
.controls{ position:absolute; right:12px; bottom:12px; display:flex; gap:8px; z-index:2; }
</style>
