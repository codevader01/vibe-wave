"""Real-time EQ, shelves, balance, ReplayGain, and a small reverb.

Filters are the Audio EQ Cookbook biquads (Bristow-Johnson), run with
scipy.signal.lfilter. Flat settings are a wire: the samples are not rewritten
by a filter. Boosts above +3 dB pull the preamp down a little so the stream
does not clip.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

from vibewave.constants import EQ_BANDS


def _normalize(b0, b1, b2, a0, a1, a2) -> tuple[np.ndarray, np.ndarray]:
    b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return b, a


def design_peaking(frequency: float, gain_db: float, sample_rate: int, q: float = 1.15):
    """Peaking EQ. 0 dB is exactly unity when A == 1."""
    amp = 10 ** (gain_db / 40)
    omega = 2 * math.pi * frequency / sample_rate
    alpha = math.sin(omega) / (2 * q)
    cosine = math.cos(omega)
    return _normalize(
        1 + alpha * amp,
        -2 * cosine,
        1 - alpha * amp,
        1 + alpha / amp,
        -2 * cosine,
        1 - alpha / amp,
    )


def design_low_shelf(frequency: float, gain_db: float, sample_rate: int, slope: float = 1.0):
    amp = 10 ** (gain_db / 40)
    omega = 2 * math.pi * frequency / sample_rate
    cosine = math.cos(omega)
    sine = math.sin(omega)
    alpha = sine / 2 * math.sqrt((amp + 1 / amp) * (1 / slope - 1) + 2)
    root = 2 * math.sqrt(amp) * alpha
    return _normalize(
        amp * ((amp + 1) - (amp - 1) * cosine + root),
        2 * amp * ((amp - 1) - (amp + 1) * cosine),
        amp * ((amp + 1) - (amp - 1) * cosine - root),
        (amp + 1) + (amp - 1) * cosine + root,
        -2 * ((amp - 1) + (amp + 1) * cosine),
        (amp + 1) + (amp - 1) * cosine - root,
    )


def design_high_shelf(frequency: float, gain_db: float, sample_rate: int, slope: float = 1.0):
    amp = 10 ** (gain_db / 40)
    omega = 2 * math.pi * frequency / sample_rate
    cosine = math.cos(omega)
    sine = math.sin(omega)
    alpha = sine / 2 * math.sqrt((amp + 1 / amp) * (1 / slope - 1) + 2)
    root = 2 * math.sqrt(amp) * alpha
    return _normalize(
        amp * ((amp + 1) + (amp - 1) * cosine + root),
        -2 * amp * ((amp - 1) + (amp + 1) * cosine),
        amp * ((amp + 1) + (amp - 1) * cosine - root),
        (amp + 1) - (amp - 1) * cosine + root,
        2 * ((amp - 1) - (amp + 1) * cosine),
        (amp + 1) - (amp - 1) * cosine - root,
    )


def _comb_coeffs(delay: int, feedback: float) -> tuple[np.ndarray, np.ndarray]:
    # y[n] = x[n] + feedback * y[n - delay]
    denominator = np.zeros(delay + 1, dtype=np.float64)
    denominator[0] = 1.0
    denominator[delay] = -feedback
    numerator = np.zeros(delay + 1, dtype=np.float64)
    numerator[0] = 1.0
    return numerator, denominator


def _allpass_coeffs(delay: int, feedback: float) -> tuple[np.ndarray, np.ndarray]:
    numerator = np.zeros(delay + 1, dtype=np.float64)
    denominator = np.zeros(delay + 1, dtype=np.float64)
    numerator[0] = -feedback
    numerator[delay] = 1.0
    denominator[0] = 1.0
    denominator[delay] = -feedback
    return numerator, denominator


class DSPChain:
    """One stream's filter memory. Two chains are used when crossfading."""

    def __init__(self, sample_rate: int):
        self.sample_rate = int(sample_rate)
        self.gains = [0.0] * len(EQ_BANDS)
        self.bass_db = 0.0
        self.treble_db = 0.0
        self.preamp_db = 0.0
        self.balance = 0.0
        self.reverb_mix = 0.0
        self._bands: list[tuple] = []
        self._low = None
        self._high = None
        self._reverb = []
        self._rebuild()

    def set_params(
        self,
        *,
        gains: list[float] | None = None,
        bass_db: float | None = None,
        treble_db: float | None = None,
        preamp_db: float | None = None,
        balance: float | None = None,
        reverb_mix: float | None = None,
    ) -> None:
        if gains is not None:
            self.gains = [float(max(-12.0, min(12.0, value))) for value in gains[: len(EQ_BANDS)]]
            while len(self.gains) < len(EQ_BANDS):
                self.gains.append(0.0)
        if bass_db is not None:
            self.bass_db = float(max(-12.0, min(12.0, bass_db)))
        if treble_db is not None:
            self.treble_db = float(max(-12.0, min(12.0, treble_db)))
        if preamp_db is not None:
            self.preamp_db = float(max(-12.0, min(12.0, preamp_db)))
        if balance is not None:
            self.balance = float(max(-1.0, min(1.0, balance)))
        if reverb_mix is not None:
            self.reverb_mix = float(max(0.0, min(1.0, reverb_mix)))
        self._rebuild()

    def _keep(self, previous, coeffs):
        if previous is None:
            return (coeffs[0], coeffs[1], np.zeros(2), np.zeros(2))
        _b, _a, left, right = previous
        return (coeffs[0], coeffs[1], left, right)

    def _rebuild(self) -> None:
        rate = self.sample_rate
        nyquist = rate * 0.47
        new_bands = []
        for index, (_label, frequency) in enumerate(EQ_BANDS):
            gain = self.gains[index]
            if abs(gain) < 0.05 or frequency >= nyquist:
                new_bands.append(None)
                continue
            coeffs = design_peaking(min(frequency, nyquist - 1), gain, rate)
            previous = self._bands[index] if index < len(self._bands) else None
            new_bands.append(self._keep(previous if previous else None, coeffs))
        self._bands = new_bands

        if abs(self.bass_db) >= 0.05:
            coeffs = design_low_shelf(min(120.0, nyquist - 1), self.bass_db, rate)
            self._low = self._keep(self._low, coeffs)
        else:
            self._low = None
        treble_freq = min(8000.0, nyquist * 0.7)
        if abs(self.treble_db) >= 0.05 and treble_freq > 80:
            coeffs = design_high_shelf(treble_freq, self.treble_db, rate)
            self._high = self._keep(self._high, coeffs)
        else:
            self._high = None

        if self.reverb_mix > 0.001 and not self._reverb:
            self._reverb = self._make_reverb()

    def _make_reverb(self) -> list[tuple]:
        rate = self.sample_rate
        scale = rate / 44100
        combs = [int(delay * scale) for delay in (1116, 1188, 1277, 1356)]
        allpasses = [int(delay * scale) for delay in (225, 341)]
        stages = []
        for delay in combs:
            numerator, denominator = _comb_coeffs(max(8, delay), 0.62)
            stages.append((numerator, denominator, np.zeros(len(denominator) - 1), np.zeros(len(denominator) - 1)))
        for delay in allpasses:
            numerator, denominator = _allpass_coeffs(max(8, delay), 0.5)
            stages.append((numerator, denominator, np.zeros(len(denominator) - 1), np.zeros(len(denominator) - 1)))
        return stages

    @property
    def neutral(self) -> bool:
        return (
            all(abs(gain) < 0.05 for gain in self.gains)
            and abs(self.bass_db) < 0.05
            and abs(self.treble_db) < 0.05
            and self.reverb_mix <= 0.001
            and abs(self.balance) < 0.001
            and abs(self.preamp_db) < 0.05
        )

    def _run(self, samples: np.ndarray, stage) -> np.ndarray:
        numerator, denominator, left, right = stage
        out_left, new_left = lfilter(numerator, denominator, samples[:, 0], zi=left)
        out_right, new_right = lfilter(numerator, denominator, samples[:, 1], zi=right)
        stage[2][:] = new_left
        stage[3][:] = new_right
        stacked = np.column_stack((out_left, out_right))
        return stacked

    def compensation_db(self) -> float:
        """Turn large boosts down so the safety clip is not doing all the work."""
        boost = max([0.0, *self.gains, self.bass_db, self.treble_db, self.preamp_db])
        return max(0.0, boost - 3.0) * 0.6

    def process(self, audio: np.ndarray, extra_gain_db: float = 0.0) -> np.ndarray:
        """Process stereo float audio. `extra_gain_db` is ReplayGain for this file."""
        if audio.size == 0:
            return audio.astype(np.float32, copy=False)
        samples = np.asarray(audio, dtype=np.float64)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("DSP expects stereo frames shaped (n, 2)")
        gain_db = extra_gain_db + self.preamp_db - self.compensation_db()
        if abs(gain_db) > 0.01:
            samples = samples * (10 ** (gain_db / 20))
        else:
            samples = samples.copy()
        if self._low is not None:
            samples = self._run(samples, self._low)
        for stage in self._bands:
            if stage is not None:
                samples = self._run(samples, stage)
        if self._high is not None:
            samples = self._run(samples, self._high)
        if self.reverb_mix > 0.001 and self._reverb:
            samples = self._apply_reverb(samples)
        if abs(self.balance) > 0.001:
            # Unity at center. Full left or right mutes the other channel.
            left = 1.0 if self.balance <= 0 else 1.0 - self.balance
            right = 1.0 if self.balance >= 0 else 1.0 + self.balance
            samples[:, 0] *= left
            samples[:, 1] *= right
        np.clip(samples, -1.0, 1.0, out=samples)
        return samples.astype(np.float32)

    def _apply_reverb(self, samples: np.ndarray) -> np.ndarray:
        # Four parallel combs, then two series allpasses, on a mono sum.
        # The wet signal is mixed back in; the dry signal is what the EQ produced.
        mono = (samples[:, 0] + samples[:, 1]) * 0.5
        wet = np.zeros_like(mono)
        combs = self._reverb[:4]
        for stage in combs:
            numerator, denominator, state, _unused = stage
            filtered, new_state = lfilter(numerator, denominator, mono, zi=state)
            stage[2][:] = new_state
            wet += filtered
        wet *= 0.25
        for stage in self._reverb[4:]:
            numerator, denominator, state, _unused = stage
            wet, new_state = lfilter(numerator, denominator, wet, zi=state)
            stage[2][:] = new_state
        mix = self.reverb_mix
        left = samples[:, 0] * (1 - mix) + wet * mix
        # A few milliseconds of difference keeps the wet signal from collapsing to mono.
        shift = min(len(wet) // 8, int(self.sample_rate * 0.012))
        wet_right = np.roll(wet, shift) if shift else wet
        right = samples[:, 1] * (1 - mix) + wet_right * mix
        return np.column_stack((left, right))
