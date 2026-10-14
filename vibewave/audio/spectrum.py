"""Live spectrum from the samples that are about to be heard.

This is an FFT of the playback buffer, grouped into log-spaced bands.
It is not a decorative animation.
"""

from __future__ import annotations

import numpy as np


def band_energies(stereo: np.ndarray, sample_rate: int, n_bars: int = 40) -> np.ndarray:
    """Return `n_bars` magnitudes from about 30 Hz to 16 kHz."""
    bars = np.zeros(n_bars, dtype=np.float32)
    if stereo is None or len(stereo) < 64 or sample_rate <= 0:
        return bars
    mono = stereo.mean(axis=1).astype(np.float64)
    window = np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(mono * window))
    frequencies = np.fft.rfftfreq(len(mono), 1 / sample_rate)
    low = 30.0
    high = min(16000.0, sample_rate * 0.45)
    if high <= low:
        return bars
    edges = np.logspace(np.log10(low), np.log10(high), n_bars + 1)
    for index in range(n_bars):
        mask = (frequencies >= edges[index]) & (frequencies < edges[index + 1])
        if np.any(mask):
            bars[index] = float(np.mean(spectrum[mask]))
    compressed = np.log1p(bars * 8.0).astype(np.float32)
    return compressed
