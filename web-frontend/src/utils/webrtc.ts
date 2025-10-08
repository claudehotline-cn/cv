export interface WebRTCConfig {
  signalingServerUrl: string;
  stunServers: string[];
  turnServers?: RTCIceServer[];
}

export interface SignalingMessage {
  type: string;
  client_id?: string;
  data?: any;
  message?: string;
  timestamp?: number;
}

export class WebRTCClient {
  private peerConnection: RTCPeerConnection | null = null;
  private signalingSocket: WebSocket | null = null;
  private remoteVideo: HTMLVideoElement | null = null;
  private clientId: string | null = null;
  private pendingIceCandidates: any[] = [];
  private pendingStream: MediaStream | null = null;
  private dataChannel: RTCDataChannel | null = null;
  private jpegBuffer: ArrayBuffer[] = [];
  private currentFrameSize = 0;
  private frameReceiving = false;
  private dataChannelReady = false;
  private localCandCount = 0;
  private remoteCandCount = 0;
  private localCandList: string[] = [];
  private remoteCandList: string[] = [];
  private statsTimer: any = null;

  private config: WebRTCConfig;
  private onConnected?: () => void;
  private onDisconnected?: () => void;
  private onVideoStream?: (stream: MediaStream) => void;
  private onJpegFrame?: (jpegData: ArrayBuffer) => void;
  private onError?: (error: string) => void;

  constructor(config: WebRTCConfig) {
    this.config = config;
    // 覆盖原有 handleIceCandidate 为更健壮的运行时实现，避免浏览器对异常候选报错
    // @ts-ignore
    (this as any).handleIceCandidate = this.handleIceCandidateRuntime.bind(this);
  }

  private trunc(text: string, max = 1024): string {
    if (!text) return text;
    return text.length <= max ? text : text.slice(0, max) + `... (${text.length - max} bytes truncated)`;
  }

  async connect(): Promise<boolean> {
    try {
      console.log("🔌 开始WebRTC连接...");
      console.log("🌐 连接信令服务器:", this.config.signalingServerUrl || "ws://127.0.0.1:8083");
      console.log("🧊 ICE 配置: STUN=", (this.config.stunServers || []).length, (this.config.stunServers || []));
      await this.connectWithRetry();
      this.createPeerConnection();
      console.log("✅ WebRTC连接初始化成功");
      return true;
    } catch (e) {
      console.error("❌ WebRTC连接失败:", e);
      this.onError?.(e instanceof Error ? e.message : "Unknown error");
      return false;
    }
  }

  disconnect(): void {
    this.peerConnection?.close();
    this.peerConnection = null;
    this.signalingSocket?.close();
    this.signalingSocket = null;
    this.dataChannelReady = false;
    this.onDisconnected?.();
  }

  setVideoElement(video: HTMLVideoElement): void {
    console.log("🎥 设置视频元素");
    this.remoteVideo = video;
    if (this.pendingStream && this.remoteVideo) {
      if (this.remoteVideo.srcObject !== this.pendingStream) {
        this.remoteVideo.srcObject = this.pendingStream;
        this.remoteVideo.muted = true;
        this.remoteVideo.autoplay = true;
        this.remoteVideo.play().catch(() => {});
      }
    }
  }

  setEventHandlers(h: {
    onConnected?: () => void;
    onDisconnected?: () => void;
    onVideoStream?: (stream: MediaStream) => void;
    onJpegFrame?: (jpegData: ArrayBuffer) => void;
    onError?: (error: string) => void;
  }): void {
    this.onConnected = h.onConnected;
    this.onDisconnected = h.onDisconnected;
    this.onVideoStream = h.onVideoStream;
    this.onJpegFrame = h.onJpegFrame;
    this.onError = h.onError;
  }

  requestVideoStream(sourceId?: string): void {
    if (!this.signalingSocket || this.signalingSocket.readyState !== WebSocket.OPEN) return;
    if (this.dataChannelReady && this.peerConnection && this.peerConnection.connectionState === "connected") {
      const msg: SignalingMessage = { type: "switch_source", data: { source_id: sourceId }, timestamp: Date.now() };
      console.log("🔁 切换视频源，source_id:", sourceId);
      this.signalingSocket.send(JSON.stringify(msg));
    } else {
      const msg: SignalingMessage = { type: "request_offer", data: sourceId ? { source_id: sourceId } : undefined, timestamp: Date.now() };
      console.log("📤 请求视频流，source_id:", sourceId);
      this.signalingSocket.send(JSON.stringify(msg));
    }
  }

  private async connectSignalingServer(): Promise<void> {
    const url = this.config.signalingServerUrl || "ws://127.0.0.1:8083";
    return new Promise((resolve, reject) => {
      const sock = new WebSocket(url);
      sock.onopen = () => {
        console.log("🔗 WebSocket已打开, readyState:", sock.readyState);
        this.signalingSocket = sock;
        setTimeout(() => this.authenticate(), 50);
        resolve();
      };
      sock.onclose = (ev) => {
        console.warn("⚠️ WebSocket已关闭", ev.code, ev.reason);
        this.onDisconnected?.();
      };
      sock.onerror = () => reject(new Error("Signaling server connection failed"));
      sock.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);
          const t = raw?.type || "<unknown>";
          console.log("📩 收到信令消息:", t, `len=${(event.data as string).length}`);
          try { console.log("[Signaling<-] payload:", this.trunc(String(event.data), 1024)); } catch {}
          this.handleSignalingMessage(raw);
        } catch (err) {
          console.error("❌ 解析WebSocket消息失败:", err, event.data);
        }
      };
      setTimeout(() => { if (sock.readyState !== WebSocket.OPEN) reject(new Error("timeout")); }, 5000);
    });
  }

  private async connectWithRetry(maxAttempts = 10, delayMs = 500): Promise<void> {
    let lastErr: any = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        await this.connectSignalingServer();
        if (this.signalingSocket && this.signalingSocket.readyState === WebSocket.OPEN) return;
      } catch (e) {
        lastErr = e;
        console.warn(`🔁 信令连接重试 ${attempt}/${maxAttempts} 失败:`, (e as Error)?.message || e);
      }
      await new Promise((r) => setTimeout(r, delayMs));
    }
    throw lastErr || new Error("Failed to connect signaling after retries");
  }

  private authenticate(): void {
    const auth: SignalingMessage = { type: "auth", data: { client_type: "web_client", client_id: `web_${Date.now()}` }, timestamp: Date.now() };
    console.log("🔐 发送认证消息:", JSON.stringify(auth));
    this.signalingSocket?.send(JSON.stringify(auth));
  }

  private createPeerConnection(): void {
    const pc = new RTCPeerConnection({ iceServers: this.config.stunServers.map((u) => ({ urls: u })) });
    this.peerConnection = pc;
    pc.onconnectionstatechange = () => {
      console.log("📶 PeerConnection state:", pc.connectionState);
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") this.dumpIceStats();
    };
    pc.oniceconnectionstatechange = () => {
      console.log("🧊 ICE connection state:", pc.iceConnectionState);
      if (pc.iceConnectionState === "failed" || pc.iceConnectionState === "disconnected") this.dumpIceStats();
    };
    pc.onicegatheringstatechange = () => {
      console.log("🧊 ICE gathering state:", pc.iceGatheringState, "(local candidates=", this.localCandCount, ")");
      if (pc.iceGatheringState === "complete") {
        if (this.localCandCount === 0) {
          console.warn("⚠️ 本地候选为空（end-of-candidates）。请检查浏览器策略/防火墙/网络。");
        }
        this.dumpCandidates("gather-complete");
      }
    };
    pc.onsignalingstatechange = () => console.log("📶 Signaling state:", pc.signalingState);
    (pc as any).onicecandidateerror = (e: any) => {
      try { console.error("❌ onicecandidateerror:", e?.errorText || e); } catch { /* ignore */ }
    };
    pc.onicecandidate = (ev) => {
      const cand = ev.candidate?.candidate || null;
      if (!ev.candidate) {
        console.log("🧊 Local ICE candidate: null (end-of-candidates)");
        this.dumpCandidates("end-of-candidates");
        return;
      }
      this.localCandCount++;
      const text = ev.candidate.candidate;
      this.localCandList.push(text);
      const typ = / typ ([a-zA-Z]+)/.exec(text)?.[1] || "?";
      const proto = / UDP | TCP /i.test(text) ? (text.toUpperCase().includes("UDP")?"udp":"tcp") : "?";
      const isMdns = text.includes(".local");
      console.log("🧊 Local ICE candidate:", text);
      console.log("🧊 发送本地候选: typ=", typ, " proto=", proto, " mdns=", isMdns, " len=", text.length);
      if (this.signalingSocket && this.signalingSocket.readyState === WebSocket.OPEN) {
        const msg: SignalingMessage = {
          type: "ice_candidate",
          data: {
            candidate: text,
            sdpMid: ev.candidate.sdpMid,
            sdpMLineIndex: ev.candidate.sdpMLineIndex,
          },
          timestamp: Date.now(),
        };
        try {
          const payload = JSON.stringify(msg);
          console.log("[Signaling->] ICE candidate:", this.trunc(payload, 512));
          this.signalingSocket.send(payload);
        } catch { /* ignore */ }
      }
    };

    pc.ondatachannel = (event) => {
      console.log("📦 收到数据通道:", event.channel.label);
      this.dataChannel = event.channel; this.dataChannel.binaryType = "arraybuffer";
      this.dataChannel.onopen = () => { console.log("📦 数据通道已开"); this.dataChannelReady = true; };
      this.dataChannel.onclose = () => { console.log("📦 数据通道已关"); this.dataChannelReady = false; };
      this.dataChannel.onerror = (e) => console.error("📦 数据通道错误:", e);
      this.dataChannel.onmessage = (ev) => this.handleDataChannelMessage(ev.data as ArrayBuffer);
    };

    pc.ontrack = (ev) => {
      const [stream] = ev.streams; console.log("🎞️ 收到远端track:", ev.track.kind, "streams:", ev.streams.length);
      if (stream) {
        this.pendingStream = stream;
        if (this.remoteVideo) {
          if (this.remoteVideo.srcObject !== stream) {
            this.remoteVideo.srcObject = stream;
            this.remoteVideo.muted = true;
            this.remoteVideo.autoplay = true;
            (this.remoteVideo as any).playsInline = true;
            this.remoteVideo.play().catch(() => {});
          }
        }
        this.onVideoStream?.(stream);
      }
    };
  }

  private async handleSignalingMessage(message: SignalingMessage): Promise<void> {
    const t = message.type;
    try {
      switch (t) {
        case "welcome": console.log("👋 收到 welcome，准备认证"); break;
        case "auth_success": console.log("✅ 认证成功，client_id:", message.client_id); this.clientId = message.client_id || null; this.onConnected?.(); break;
        case "offer":
          {
            const sdp: string = message?.data?.sdp || "";
            const hasH264 = /H264\/90000/.test(sdp);
            const hasFmtp = /a=fmtp:.*packetization-mode=1/.test(sdp);
            console.log("📨 收到 offer，sdpLen=", sdp.length, " H264=", hasH264, " fmtp=", hasFmtp);
            await this.handleOffer(message.data);
          }
          break;
        case "ice_candidate":
          {
            const text = String(message?.data?.candidate || "");
            const typ = / typ ([a-zA-Z]+)/.exec(text)?.[1] || "?";
            const isMdns = text.includes(".local");
            console.log("🧊 收到远端候选: typ=", typ, " mdns=", isMdns, " len=", text.length);
            try { console.log("[Signaling<-] remote ICE:", this.trunc(text, 512)); } catch {}
            this.remoteCandList.push(text);
            if (this.peerConnection?.remoteDescription) await this.handleIceCandidate(message.data); else this.pendingIceCandidates.push(message.data);
          }
          break;
        default: console.log("ℹ️ 未处理消息:", t);
      }
    } catch (e) { console.error("❌ 处理信令失败:", e); this.onError?.(e instanceof Error ? e.message : "Signaling error"); }
  }

  private async handleOffer(offerData: any): Promise<void> {
    if (!this.peerConnection) throw new Error("PeerConnection not initialized");
    const pc = this.peerConnection; console.log("📨 收到 offer，开始应答... sdpLen=", (offerData?.sdp || "").length);
    const sdp: string = String(offerData?.sdp || "");
    if (pc.signalingState !== "stable") { try { await (pc as any).setLocalDescription({ type: "rollback" } as any); console.log("↩️ 已执行 rollback"); } catch (e) { console.warn("rollback 失败(可忽略)", e); } }
    await pc.setRemoteDescription(new RTCSessionDescription({ type: "offer", sdp }));
    const answer = await pc.createAnswer({ offerToReceiveVideo: true, offerToReceiveAudio: false });
    if (answer.sdp) answer.sdp = answer.sdp.replace(/a=inactive/g, "a=recvonly");
    await pc.setLocalDescription(answer);
    const msg: SignalingMessage = { type: "answer", data: { type: "answer", sdp: answer.sdp }, timestamp: Date.now() };
    console.log("📤 发送 answer，sdpLen=", (answer.sdp || "").length); this.signalingSocket?.send(JSON.stringify(msg));
    for (const c of this.pendingIceCandidates.splice(0)) { try { await this.handleIceCandidate(c); } catch (e) { console.warn("⚠️ 重放ICE失败:", e); } }
  }

  private async handleIceCandidate(candidateData: any): Promise<void> {
    if (!this.peerConnection) return; if (!candidateData?.candidate) return;
    const cand = new RTCIceCandidate({ candidate: candidateData.candidate, sdpMid: candidateData.sdpMid, sdpMLineIndex: candidateData.sdpMLineIndex });
    console.log("🧊 应用远端ICE:", candidateData.candidate.slice(0, 120)); await this.peerConnection.addIceCandidate(cand);
    this.remoteCandCount++;
  }

  private handleDataChannelMessage(data: ArrayBuffer): void {
    if (!this.frameReceiving) {
      if (data.byteLength >= 4) { const dv = new DataView(data); this.currentFrameSize = (dv.getUint8(0) << 24) | (dv.getUint8(1) << 16) | (dv.getUint8(2) << 8) | dv.getUint8(3); this.frameReceiving = true; this.jpegBuffer = []; if (data.byteLength > 4) this.jpegBuffer.push(data.slice(4)); }
      else { console.warn("⚠️ 数据包过小，无法读取帧头:", data.byteLength); }
    } else { this.jpegBuffer.push(data); }
    let received = 0; for (const b of this.jpegBuffer) received += b.byteLength;
    if (this.frameReceiving && received >= this.currentFrameSize) {
      const full = new ArrayBuffer(this.currentFrameSize); const view = new Uint8Array(full); let off = 0; for (const b of this.jpegBuffer) { const v = new Uint8Array(b); const n = Math.min(v.length, this.currentFrameSize - off); view.set(v.slice(0, n), off); off += n; if (off >= this.currentFrameSize) break; }
      if (view[0] === 0xff && view[1] === 0xd8) this.onJpegFrame?.(full); else console.error("❌ JPEG帧头校验失败", Array.from(view.slice(0, 8)).map(x=>x.toString(16)).join(" "));
      this.frameReceiving = false; this.currentFrameSize = 0; this.jpegBuffer = [];
    }
  }

  // 更健壮的 ICE 重放处理：规范化 candidate 文本和 sdpMid，并提供回退路径
  private async handleIceCandidateRuntime(candidateData: any): Promise<void> {
    if (!this.peerConnection) return; if (!candidateData?.candidate) return;
    const pc = this.peerConnection;
    // 1) 去掉可能的 "a=" 前缀
    let candText: string = String(candidateData.candidate || "");
    if (candText.startsWith("a=")) candText = candText.slice(2);
    // 2) 校正 sdpMid：若与现有 transceivers 不匹配，则重写为视频 mid 或首个 mid
    let sdpMid: string | undefined = candidateData.sdpMid;
    try {
      const tids = pc.getTransceivers?.() ? pc.getTransceivers().map((t: RTCRtpTransceiver) => t.mid).filter(Boolean) as string[] : [];
      if (!sdpMid || (tids.length && !tids.includes(String(sdpMid)))) {
        const videoMid = pc.getTransceivers?.().find((t: RTCRtpTransceiver) => t.receiver?.track?.kind === "video")?.mid;
        const newMid = (videoMid || tids[0]);
        if (newMid) {
          console.warn("⚠️ 重写 ICE sdpMid:", sdpMid, "->", newMid);
          sdpMid = newMid;
        }
      }
    } catch {}
    console.log("?? 应用远端ICE:", candText.slice(0, 160), "mid=", sdpMid, "mLine=", candidateData.sdpMLineIndex);
    try {
      const cand = new RTCIceCandidate({ candidate: candText, sdpMid, sdpMLineIndex: candidateData.sdpMLineIndex });
      await pc.addIceCandidate(cand);
      this.remoteCandCount++;
    } catch (e) {
      console.error("❌ addIceCandidate 失败，尝试回退:", e);
      // 回退1：仅用 sdpMLineIndex
      try {
        const cand = new RTCIceCandidate({ candidate: candText, sdpMLineIndex: candidateData.sdpMLineIndex });
        await pc.addIceCandidate(cand);
        this.remoteCandCount++;
        console.warn("✅ 回退成功：使用 sdpMLineIndex 添加 ICE");
        return;
      } catch {}
      // 回退2：仅用 candidate
      try {
        const cand = new RTCIceCandidate({ candidate: candText } as any);
        await pc.addIceCandidate(cand);
        this.remoteCandCount++;
        console.warn("✅ 回退成功：仅 candidate 添加 ICE");
      } catch (e2) {
        console.error("❌ 所有回退均失败:", e2, "candidate=", candText);
      }
    }
  }

  // 诊断：输出当前 ICE 统计信息
  private async dumpIceStats(): Promise<void> {
    try {
      const pc = this.peerConnection;
      if (!pc) return;
      const stats = await pc.getStats();
      let selectedPairId: string | null = null;
      const byId: Record<string, any> = {};
      stats.forEach((s: any) => { byId[s.id] = s; });
      stats.forEach((s: any) => { if (s.type === "transport" && s.selectedCandidatePairId) selectedPairId = s.selectedCandidatePairId; });
      if (!selectedPairId) {
        stats.forEach((s: any) => { if (s.type === "candidate-pair" && (s.selected || s.nominated)) selectedPairId = s.id; });
      }
      const pair = selectedPairId ? byId[selectedPairId] : null;
      const local = pair && pair.localCandidateId ? byId[pair.localCandidateId] : null;
      const remote = pair && pair.remoteCandidateId ? byId[pair.remoteCandidateId] : null;
      console.log("🔎 ICE 调试: localCands=", this.localCandCount, " remoteCands=", this.remoteCandCount);
      console.log("🔎 选中候选: pairId=", selectedPairId, pair || "<none>");
      console.log("🔎 本地候选:", local ? {type: local.candidateType, protocol: local.protocol, address: local.address, port: local.port} : "<none>");
      console.log("🔎 远端候选:", remote ? {type: remote.candidateType, protocol: remote.protocol, address: remote.address, port: remote.port} : "<none>");
    } catch (e) {
      console.warn("⚠️ dumpIceStats 失败:", e);
    }
  }

  private dumpCandidates(phase: string): void {
    try {
      const head = (arr: string[], max = 4) => arr.slice(0, max).map((s) => s.length > 200 ? s.slice(0, 200) + '…' : s);
      console.log(`🧊 [${phase}] 本地候选(${this.localCandList.length}):`, head(this.localCandList));
      console.log(`🧊 [${phase}] 远端候选(${this.remoteCandList.length}):`, head(this.remoteCandList));
    } catch {}
  }
}

