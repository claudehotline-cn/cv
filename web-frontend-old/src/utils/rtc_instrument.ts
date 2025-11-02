// Lightweight WebRTC instrumentation: logs inbound-rtp(video) and <video> playback events
// Automatically hooks RTCPeerConnection and binds listeners, no app code changes needed.

(() => {
  try {
    const g: any = window as any;
    if (g.__rtcInstrumentInstalled) return;
    g.__rtcInstrumentInstalled = true;

    const OrigPC = (window as any).RTCPeerConnection;
    if (!OrigPC) return;

    function bindVideoEvents(v: HTMLVideoElement) {
      try {
        const log = (tag: string) => console.log(`🎥 video ${tag}:`, {
          readyState: v.readyState,
          width: v.videoWidth,
          height: v.videoHeight,
          paused: v.paused,
          err: (v as any).error?.message
        });
        v.onloadedmetadata = () => log('loadedmetadata');
        v.oncanplay        = () => log('canplay');
        v.onplaying        = () => log('playing');
        v.onwaiting        = () => log('waiting');
        v.onstalled        = () => log('stalled');
        v.onerror          = () => log('error');
        (v as any).onresize= () => log('resize');
      } catch {}
    }

    function startInboundStatsProbe(pc: RTCPeerConnection) {
      try {
        if ((g.__rtpTimer)) return;
        let lastBytes = 0, lastPkts = 0, lastFrames = 0;
        g.__rtpTimer = setInterval(async () => {
          try {
            const stats = await pc.getStats();
            let inbound: any = null;
            stats.forEach((s: any) => {
              if (s.type === 'inbound-rtp' && (s.kind === 'video' || /video/i.test(String(s.mimeType||'')))) inbound = s;
            });
            if (inbound) {
              const bytes = inbound.bytesReceived || 0;
              const pkts  = inbound.packetsReceived || 0;
              const frames= (inbound.framesDecoded ?? inbound.framesReceived ?? 0);
              const dropped = inbound.framesDropped || 0;
              const fps   = inbound.framesPerSecond ?? 0;
              console.log(`📈 inbound-rtp video: +${bytes-lastBytes}B +${pkts-lastPkts}pkts +${frames-lastFrames}frames (bytes=${bytes}, frames=${frames}, dropped=${dropped}, fps=${fps})`);
              lastBytes = bytes; lastPkts = pkts; lastFrames = frames;
            } else {
              console.log('📈 inbound-rtp video: <none>');
            }
          } catch (e) { console.warn('stats probe error:', e); }
        }, 1000);
      } catch {}
    }

    (window as any).RTCPeerConnection = function(this: any, config: any) {
      const pc: RTCPeerConnection = new OrigPC(config);
      try { (window as any).__pc = pc; } catch {}
      try {
        pc.addEventListener('track', (ev: any) => {
          try {
            const videoEl = document.querySelector('video.video-stream') as HTMLVideoElement | null;
            if (videoEl) bindVideoEvents(videoEl);
          } catch {}
          startInboundStatsProbe(pc);
        });
      } catch {}
      return pc as any;
    } as any;
    (window as any).RTCPeerConnection.prototype = OrigPC.prototype;
    console.log('[RTC] instrumentation installed: window.__pc will track latest RTCPeerConnection');
  } catch (e) {
    // no-op in non-browser env
  }
})();

