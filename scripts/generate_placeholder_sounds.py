"""Generate placeholder click + celebration WAVs using only stdlib.

These are throwaway sounds so the demo works without depending on an
external download. Swap them for a real CC0 set (e.g. Mixkit) when you
want something nicer — just keep the filenames.

Run from the project root:
    .venv\\Scripts\\python.exe scripts\\generate_placeholder_sounds.py
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100  # CD quality; HTML5 Audio handles it without resampling
AMPLITUDE = 20000    # int16 range is +/- 32767; leave headroom to avoid clipping


def write_wav(path: Path, samples: list[int]) -> None:
    """Write 16-bit mono PCM samples to a .wav file at SAMPLE_RATE."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        # ``"<h"`` packs each int as little-endian signed 16-bit — the
        # standard PCM WAV sample format.
        frames = b"".join(struct.pack("<h", s) for s in samples)
        w.writeframes(frames)


def make_click(duration_s: float = 0.04) -> list[int]:
    """Short ~40ms tone burst with exponential decay — feels like a UI tap."""
    n = int(SAMPLE_RATE * duration_s)
    freq = 1200.0  # bright but not piercing
    samples: list[int] = []
    for i in range(n):
        t = i / SAMPLE_RATE
        # Fast exponential decay: e^(-60t) reaches ~5% by 50ms.
        envelope = math.exp(-t * 60)
        value = math.sin(2 * math.pi * freq * t) * envelope * AMPLITUDE
        samples.append(int(max(-32767, min(32767, value))))
    return samples


def make_celebrate(total_duration_s: float = 1.2) -> list[int]:
    """4-note ascending major arpeggio (C5, E5, G5, C6) for a tada feel."""
    notes_hz = [523.25, 659.25, 783.99, 1046.50]
    note_duration_s = total_duration_s / len(notes_hz)
    samples: list[int] = []
    for note in notes_hz:
        n = int(SAMPLE_RATE * note_duration_s)
        for i in range(n):
            t = i / SAMPLE_RATE
            # sin(pi * x) gives a smooth attack-and-release shape; the
            # sqrt softens the edges so notes don't click between them.
            envelope = math.sin(math.pi * (i / n)) ** 0.5
            value = math.sin(2 * math.pi * note * t) * envelope * AMPLITUDE
            samples.append(int(max(-32767, min(32767, value))))
    return samples


if __name__ == "__main__":
    sounds_dir = Path(__file__).resolve().parent.parent / "static" / "sounds"
    sounds_dir.mkdir(parents=True, exist_ok=True)
    write_wav(sounds_dir / "click.wav", make_click())
    write_wav(sounds_dir / "celebrate.wav", make_celebrate())
    print(f"wrote {sounds_dir / 'click.wav'}")
    print(f"wrote {sounds_dir / 'celebrate.wav'}")
