type MicCallback = (data: Float32Array) => void;
type LipSyncCallback = (volume: number) => void;

/**
 * Manages microphone capture and audio playback with lip sync support.
 * Lip sync uses pre-computed volume arrays from the backend, matching
 * the original frontend implementation.
 */
export class AudioManager {
  private baseUrl: string;
  private audioContext: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private micProcessor: ScriptProcessorNode | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private currentAudio: HTMLAudioElement | null = null;
  private currentLipSyncInterval: ReturnType<typeof setInterval> | null = null;
  private selectedDeviceId: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  /**
   * Set the preferred microphone device ID.
   */
  setMicDeviceId(deviceId: string | null): void {
    this.selectedDeviceId = deviceId;
  }

  /**
   * List available audio input devices.
   */
  async listMicDevices(): Promise<MediaDeviceInfo[]> {
    // Request mic permission first so device labels are populated
    try {
      const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      for (const track of tempStream.getTracks()) track.stop();
    } catch {
      // Permission denied – return whatever we can
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  }

  private async getAudioContext(): Promise<AudioContext> {
    if (!this.audioContext) {
      this.audioContext = new AudioContext({ sampleRate: 16000 });
    }
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
    return this.audioContext;
  }

  /**
   * Start capturing microphone audio and call back with Float32Array chunks.
   */
  async startMicCapture(callback: MicCallback): Promise<void> {
    const constraints: MediaStreamConstraints = {
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        ...(this.selectedDeviceId ? { deviceId: { exact: this.selectedDeviceId } } : {}),
      },
    };

    try {
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      this.micStream = stream;
    } catch (err) {
      console.error("[audio] Failed to get mic stream:", err);
      throw err;
    }

    const ctx = await this.getAudioContext();
    this.micSource = ctx.createMediaStreamSource(this.micStream!);

    this.micProcessor = ctx.createScriptProcessor(4096, 1, 1);
    this.micProcessor.onaudioprocess = (event: AudioProcessingEvent) => {
      const data = event.inputBuffer.getChannelData(0);
      callback(new Float32Array(data));
    };

    this.micSource.connect(this.micProcessor);
    this.micProcessor.connect(ctx.destination);
    console.log("[audio] Mic capture started, device:", this.selectedDeviceId ?? "default");
  }

  /**
   * Stop microphone capture.
   */
  stopMicCapture(): void {
    if (this.micProcessor) {
      this.micProcessor.disconnect();
      this.micProcessor = null;
    }
    if (this.micSource) {
      this.micSource.disconnect();
      this.micSource = null;
    }
    if (this.micStream) {
      for (const track of this.micStream.getTracks()) {
        track.stop();
      }
      this.micStream = null;
    }
  }

  /**
   * Stop any currently playing audio.
   */
  stopPlayback(): void {
    if (this.currentLipSyncInterval) {
      clearInterval(this.currentLipSyncInterval);
      this.currentLipSyncInterval = null;
    }
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
  }

  /**
   * Play base64-encoded WAV audio using HTML5 Audio (matching original frontend).
   * Drives lip sync from the pre-computed volumes array at slice_length intervals.
   */
  async playBase64Audio(
    base64Audio: string,
    volumes: number[],
    sliceLengthMs: number,
    lipSyncCallback?: LipSyncCallback
  ): Promise<void> {
    this.stopPlayback();

    const audio = new Audio("data:audio/wav;base64," + base64Audio);
    this.currentAudio = audio;

    return new Promise<void>((resolve) => {
      // Start lip sync driven by volumes array
      if (lipSyncCallback && volumes.length > 0) {
        let i = 0;
        this.currentLipSyncInterval = setInterval(() => {
          if (i >= volumes.length) {
            if (this.currentLipSyncInterval) {
              clearInterval(this.currentLipSyncInterval);
              this.currentLipSyncInterval = null;
            }
            lipSyncCallback(0);
            return;
          }
          lipSyncCallback(volumes[i]);
          i++;
        }, sliceLengthMs);
      }

      audio.onended = () => {
        if (this.currentLipSyncInterval) {
          clearInterval(this.currentLipSyncInterval);
          this.currentLipSyncInterval = null;
        }
        if (lipSyncCallback) lipSyncCallback(0);
        this.currentAudio = null;
        resolve();
      };

      audio.onerror = (err) => {
        console.error("Audio playback error:", err);
        if (this.currentLipSyncInterval) {
          clearInterval(this.currentLipSyncInterval);
          this.currentLipSyncInterval = null;
        }
        if (lipSyncCallback) lipSyncCallback(0);
        this.currentAudio = null;
        resolve();
      };

      audio.play().catch((err) => {
        console.error("Audio play() failed:", err);
        resolve();
      });
    });
  }
}
