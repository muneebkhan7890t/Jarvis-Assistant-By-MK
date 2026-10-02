/* 16 kHz PCM microphone frames. No recording or storage in the browser. */
class RemotePCM extends AudioWorkletProcessor {
  constructor() { super(); this.samples = new Int16Array(1024); this.used = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      this.samples[this.used++] = Math.round(Math.max(-1, Math.min(1, sample)) * 32767);
      if (this.used === this.samples.length) {
        this.port.postMessage(this.samples.buffer, [this.samples.buffer]);
        this.samples = new Int16Array(1024); this.used = 0;
      }
    }
    return true;
  }
}
registerProcessor('remote-pcm', RemotePCM);
