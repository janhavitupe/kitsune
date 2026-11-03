const RATE = 16000; // Voice Transcribe takes mono 16-bit WAV at 16 or 24 kHz

/**
 * Any audio the browser can play (a webm/opus recording, an mp3 or m4a voice message) as a mono
 * 16 kHz WAV, the format Muse Voice Transcribe accepts. Null if the browser can't decode it.
 */
export async function toWav(audio: Blob): Promise<Blob | null> {
  try {
    const decoded = await new AudioContext().decodeAudioData(await audio.arrayBuffer());
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * RATE), RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded; // stereo is mixed down to the one output channel
    source.connect(offline.destination);
    source.start();
    const samples = (await offline.startRendering()).getChannelData(0);

    const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
    const text = (at: number, s: string) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
    text(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    text(8, "WAVEfmt ");
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, RATE, true);
    view.setUint32(28, RATE * 2, true); // bytes per second
    view.setUint16(32, 2, true); // bytes per frame
    view.setUint16(34, 16, true); // bits per sample
    text(36, "data");
    view.setUint32(40, samples.length * 2, true);
    samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
    return new Blob([view], { type: "audio/wav" });
  } catch {
    return null;
  }
}
