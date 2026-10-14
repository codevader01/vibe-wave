"""PortAudio playback with a decoder thread and a real DSP chain.

Kivy's SDL2 audio provider is not used. It cannot host this equalizer or
reliable seeking for FLAC, M4A, and AAC. FFmpeg decodes to float PCM,
SciPy filters it, and sounddevice plays it.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import numpy as np

from vibewave.audio.decoder import DecoderError, FFmpegDecoder
from vibewave.audio.dsp import DSPChain
from vibewave.audio.spectrum import band_energies
from vibewave.tools import ffmpeg_path

log = logging.getLogger(__name__)

_BARS = 40


class PCMRing:
    def __init__(self, capacity: int):
        self.buffer = np.zeros((capacity, 2), dtype=np.float32)
        self.capacity = capacity
        self.read_at = 0
        self.write_at = 0
        self.count = 0
        self.lock = threading.Lock()

    def free(self) -> int:
        with self.lock:
            return self.capacity - self.count

    def clear(self) -> None:
        with self.lock:
            self.read_at = 0
            self.write_at = 0
            self.count = 0

    def write(self, data: np.ndarray) -> int:
        with self.lock:
            amount = min(len(data), self.capacity - self.count)
            if amount <= 0:
                return 0
            first = min(amount, self.capacity - self.write_at)
            self.buffer[self.write_at : self.write_at + first] = data[:first]
            second = amount - first
            if second:
                self.buffer[:second] = data[first:amount]
            self.write_at = (self.write_at + amount) % self.capacity
            self.count += amount
            return amount

    def read(self, frames: int) -> tuple[np.ndarray, int]:
        out = np.zeros((frames, 2), dtype=np.float32)
        with self.lock:
            amount = min(frames, self.count)
            if amount:
                first = min(amount, self.capacity - self.read_at)
                out[:first] = self.buffer[self.read_at : self.read_at + first]
                second = amount - first
                if second:
                    out[first:amount] = self.buffer[:second]
                self.read_at = (self.read_at + amount) % self.capacity
                self.count -= amount
        return out, amount


class _Slot:
    def __init__(self, sample_rate: int, capacity: int):
        self.decoder: FFmpegDecoder | None = None
        self.ring = PCMRing(capacity)
        self.dsp = DSPChain(sample_rate)
        self.eof = False
        self.path = ""
        self.duration = 0.0
        self.replaygain_db = 0.0
        self.pending: np.ndarray | None = None
        self.error = ""

    def close(self) -> None:
        if self.decoder:
            self.decoder.close()
            self.decoder = None

    def buffered(self) -> bool:
        return self.ring.count > 0 or self.pending is not None or self.eof


class AudioEngine:
    def __init__(self):
        self.available = False
        self.error = ""
        self.sample_rate = 44100
        self.messages: queue.SimpleQueue = queue.SimpleQueue()
        self._stream = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._commands: queue.Queue = queue.Queue()
        self._retire: queue.Queue = queue.Queue()
        self._state = threading.Lock()
        self._param = threading.Lock()
        self._slot: _Slot | None = None
        self._next: _Slot | None = None
        self.playhead = 0
        self.duration = 0.0
        self.playing = False
        self.volume = 0.85
        self.muted = False
        self.fade = 1.0
        self.fade_target = 1.0
        self.fade_in_seconds = 0.25
        self.fade_out_seconds = 0.25
        self._pause_when_faded = False
        self._hold = False
        self.crossfade_seconds = 0.0
        self._xfade_heard = 0
        self._ended_sent = False
        self._params = {
            "gains": [0.0] * 7,
            "bass_db": 0.0,
            "treble_db": 0.0,
            "preamp_db": 0.0,
            "balance": 0.0,
            "reverb_mix": 0.0,
        }
        self.replaygain = True
        self.replaygain_preamp = 0.0
        self._spectrum = np.zeros(_BARS, dtype=np.float32)
        self._spec_peak = 1e-3
        self.level = 0.0
        self._capacity = 44100
        # Latest audible block. The FFT runs when the UI asks, not in the
        # PortAudio callback. An FFT there holds the GIL and makes playback late.
        self._meter = np.zeros((2048, 2), dtype=np.float32)
        self._meter_n = 0
        self._meter_lock = threading.Lock()

    def start(self) -> bool:
        if not ffmpeg_path():
            self.error = "FFmpeg was not found. Playback and conversion need it."
            return False
        try:
            import sounddevice as sd

            device = sd.query_devices(kind="output")
            rate = int(device.get("default_samplerate") or 44100)
            self.sample_rate = rate if rate >= 8000 else 44100
            self._capacity = max(self.sample_rate, int(self.sample_rate * 0.8))
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="vibewave-decode", daemon=True)
            self._thread.start()
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=2,
                dtype="float32",
                blocksize=1024,
                latency=0.08,
                callback=self._callback,
            )
            self._stream.start()
            self.available = True
            log.info("Audio device %s at %s Hz", device.get("name"), self.sample_rate)
            return True
        except Exception as exc:
            self.error = f"Audio output is unavailable ({exc})."
            log.exception("audio start failed")
            self.available = False
            return False

    def shutdown(self) -> None:
        self._running = False
        self._commands.put(("close",))
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("closing audio stream")
        if self._thread:
            self._thread.join(timeout=2)
        if self._slot:
            self._slot.close()
        if self._next:
            self._next.close()

    # -- commands from the UI thread ---------------------------------------

    def load(self, path: str, duration: float, replaygain_db: float = 0.0, autoplay: bool = True) -> None:
        self._commands.put(("load", path, float(duration or 0), float(replaygain_db or 0), bool(autoplay)))

    def prepare_next(self, path: str, duration: float, replaygain_db: float = 0.0) -> None:
        self._commands.put(("next", path, float(duration or 0), float(replaygain_db or 0)))

    def cancel_next(self) -> None:
        self._commands.put(("cancel_next",))

    def play(self) -> None:
        self._commands.put(("play",))

    def pause(self) -> None:
        self._commands.put(("pause",))

    def stop(self) -> None:
        self._commands.put(("stop",))

    def seek(self, seconds: float) -> None:
        self._commands.put(("seek", max(0.0, float(seconds))))

    def set_volume(self, volume: float) -> None:
        with self._state:
            self.volume = min(1.0, max(0.0, float(volume)))

    def set_muted(self, muted: bool) -> None:
        with self._state:
            self.muted = bool(muted)

    def set_fades(self, fade_in: float, fade_out: float) -> None:
        with self._state:
            self.fade_in_seconds = max(0.0, float(fade_in))
            self.fade_out_seconds = max(0.0, float(fade_out))

    def set_crossfade(self, seconds: float) -> None:
        with self._state:
            self.crossfade_seconds = max(0.0, min(12.0, float(seconds)))

    def set_replaygain(self, enabled: bool, preamp_db: float) -> None:
        with self._state:
            self.replaygain = bool(enabled)
            self.replaygain_preamp = max(-12.0, min(12.0, float(preamp_db)))

    def set_dsp(self, **params) -> None:
        with self._param:
            for key, value in params.items():
                if key in self._params and value is not None:
                    self._params[key] = value
        self._commands.put(("dsp",))

    def position(self) -> float:
        with self._state:
            if self.sample_rate <= 0:
                return 0.0
            return self.playhead / float(self.sample_rate)

    def is_playing(self) -> bool:
        with self._state:
            return bool(self.playing)

    def spectrum_copy(self) -> np.ndarray:
        with self._meter_lock:
            count = self._meter_n
            block = self._meter[:count].copy() if count >= 64 else None
        with self._state:
            playing = self.playing
        if block is None or not playing:
            with self._state:
                self._spectrum *= 0.82
                return self._spectrum.copy()
        bars = band_energies(block, self.sample_rate, _BARS)
        with self._state:
            self._spec_peak = max(float(bars.max()), self._spec_peak * 0.992, 1e-3)
            self._spectrum = np.clip(bars / self._spec_peak, 0, 1)
            return self._spectrum.copy()

    def output_level(self) -> float:
        with self._state:
            return float(self.level)

    # -- decoder thread -----------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            worked = self._drain()
            slot, nxt = self._slots()
            worked = self._fill(slot) or worked
            worked = self._fill(nxt) or worked
            worked = self._reap() or worked
            if not worked:
                time.sleep(0.004)

    def _reap(self) -> bool:
        closed = False
        while True:
            try:
                slot = self._retire.get_nowait()
            except queue.Empty:
                return closed
            slot.close()
            closed = True

    def _slots(self) -> tuple[_Slot | None, _Slot | None]:
        with self._state:
            return self._slot, self._next

    def _drain(self) -> bool:
        worked = False
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return worked
            worked = True
            kind = command[0]
            try:
                if kind == "load":
                    self._load(*command[1:])
                elif kind == "next":
                    self._prepare_next(*command[1:])
                elif kind == "cancel_next":
                    self._cancel_next()
                elif kind == "seek":
                    self._seek(command[1])
                elif kind == "play":
                    self._play()
                elif kind == "pause":
                    self._pause()
                elif kind == "stop":
                    self._stop()
                elif kind == "dsp":
                    self._apply_dsp()
                elif kind == "close":
                    self._running = False
                    return True
            except Exception as exc:
                log.exception("audio command %s", kind)
                self.messages.put(("error", str(exc)))
        return worked

    def _new_slot(self, path: str, duration: float, replaygain_db: float, start: float) -> _Slot:
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise DecoderError("FFmpeg was not found.")
        slot = _Slot(self.sample_rate, self._capacity)
        slot.path = path
        slot.duration = duration
        slot.replaygain_db = replaygain_db
        slot.decoder = FFmpegDecoder(ffmpeg, path, self.sample_rate, start)
        self._push_dsp(slot.dsp)
        return slot

    def _push_dsp(self, chain: DSPChain) -> None:
        with self._param:
            params = dict(self._params)
        chain.set_params(**params)

    def _apply_dsp(self) -> None:
        slot, nxt = self._slots()
        if slot:
            self._push_dsp(slot.dsp)
        if nxt:
            self._push_dsp(nxt.dsp)

    def _load(self, path: str, duration: float, replaygain_db: float, autoplay: bool) -> None:
        self._cancel_next()
        old = None
        with self._state:
            old = self._slot
            self._slot = None
            self._hold = True
            self.playhead = 0
            self.duration = duration
            self._ended_sent = False
            self._xfade_heard = 0
            self.playing = False
        if old:
            old.close()
        try:
            slot = self._new_slot(path, duration, replaygain_db, 0.0)
        except DecoderError as exc:
            with self._state:
                self._hold = False
            self.messages.put(("error", str(exc)))
            return
        self._prefill(slot)
        with self._state:
            self._slot = slot
            self.duration = duration
            # Start at full level. A fade-in here is heard as the file loading late.
            if autoplay:
                self.fade = 1.0
                self.fade_target = 1.0
                self.playing = True
            else:
                self.fade = 0.0
                self.fade_target = 0.0
                self.playing = False
            self._pause_when_faded = False
            self._hold = False
        if slot.eof and slot.ring.count == 0:
            self.messages.put(("error", "This file did not produce any audio."))

    def _prepare_next(self, path: str, duration: float, replaygain_db: float) -> None:
        self._cancel_next()
        try:
            slot = self._new_slot(path, duration, replaygain_db, 0.0)
        except DecoderError as exc:
            self.messages.put(("error", str(exc)))
            return
        with self._state:
            self._next = slot
            self._xfade_heard = 0

    def _cancel_next(self) -> None:
        with self._state:
            slot = self._next
            self._next = None
            self._xfade_heard = 0
        if slot:
            slot.close()

    def _seek(self, seconds: float) -> None:
        with self._state:
            slot = self._slot
            self._hold = True
            self.playhead = int(seconds * self.sample_rate)
            self._ended_sent = False
            playing = self.playing
        self._cancel_next()
        if not slot or not slot.path:
            with self._state:
                self._hold = False
            return
        slot.close()
        slot.ring.clear()
        slot.pending = None
        slot.eof = False
        slot.error = ""
        try:
            ffmpeg = ffmpeg_path()
            if not ffmpeg:
                raise DecoderError("FFmpeg was not found.")
            slot.decoder = FFmpegDecoder(ffmpeg, slot.path, self.sample_rate, seconds)
        except DecoderError as exc:
            with self._state:
                self._hold = False
            self.messages.put(("error", str(exc)))
            return
        self._prefill(slot)
        with self._state:
            self.playing = playing
            self._hold = False

    def _play(self) -> None:
        with self._state:
            if self._slot is None:
                return
            self._pause_when_faded = False
            self.fade_target = 1.0
            if self.fade_in_seconds <= 0:
                self.fade = 1.0
            self.playing = True
            self._ended_sent = False

    def _pause(self) -> None:
        with self._state:
            self.fade_target = 0.0
            self._pause_when_faded = True
            if self.fade_out_seconds <= 0:
                self.fade = 0.0
                self.playing = False

    def _stop(self) -> None:
        self._pause()
        self._seek(0.0)
        with self._state:
            self.playing = False
            self.fade = 0.0
            self.fade_target = 0.0

    def _prefill(self, slot: _Slot) -> None:
        deadline = time.time() + 0.16
        target = int(self.sample_rate * 0.05)
        while time.time() < deadline and not slot.eof and slot.ring.count < target:
            if not self._fill(slot):
                time.sleep(0.004)

    def _fill(self, slot: _Slot | None) -> bool:
        if slot is None or slot.decoder is None or slot.eof:
            return False
        if slot.pending is None and slot.ring.free() < 1024:
            return False
        if slot.pending is None:
            try:
                incoming = slot.decoder.read(2048)
            except Exception as exc:
                slot.eof = True
                slot.error = str(exc)
                return True
            if incoming is None or len(incoming) == 0:
                slot.eof = True
                return True
            try:
                slot.pending = slot.dsp.process(incoming, 0.0)
            except Exception:
                log.exception("dsp")
                slot.pending = np.clip(incoming, -1, 1)
        written = slot.ring.write(slot.pending)
        if written <= 0:
            return False
        if written >= len(slot.pending):
            slot.pending = None
        else:
            slot.pending = slot.pending[written:]
        return True

    # -- audio callback -----------------------------------------------------

    def _callback(self, outdata, frames, _time_info, _status) -> None:
        try:
            self._render(outdata, frames)
        except Exception:
            outdata.fill(0)
            log.exception("audio callback")

    def _render(self, outdata, frames: int) -> None:
        with self._state:
            slot = self._slot
            nxt = self._next
            hold = self._hold
            playing = self.playing
            playhead = self.playhead
            duration = self.duration
            fade = self.fade
            target = self.fade_target
            fade_in = self.fade_in_seconds
            fade_out = self.fade_out_seconds
            volume = 0.0 if self.muted else self.volume
            xfade = self.crossfade_seconds
            pause_when_faded = self._pause_when_faded
            replaygain = self.replaygain
            replaygain_preamp = self.replaygain_preamp
            heard = self._xfade_heard

        if hold or slot is None or (not playing and fade <= 0.001):
            outdata.fill(0)
            with self._state:
                self.level *= 0.9
            return

        audio, got = slot.ring.read(frames)
        gain_a = self._replay_gain(slot, replaygain, replaygain_preamp)
        if gain_a != 1.0:
            audio *= gain_a

        xfade_n = int(xfade * self.sample_rate)
        duration_n = int(duration * self.sample_rate) if duration > 0 else 0
        xfade_on = (
            nxt is not None
            and xfade_n > int(0.05 * self.sample_rate)
            and duration_n > xfade_n * 2
            and playhead + frames >= duration_n - xfade_n
        )
        if xfade_on and nxt is not None:
            other, got_b = nxt.ring.read(frames)
            gain_b = self._replay_gain(nxt, replaygain, replaygain_preamp)
            if gain_b != 1.0:
                other *= gain_b
            positions = playhead + np.arange(frames)
            start = duration_n - xfade_n
            mix = np.clip((positions - start) / max(1, xfade_n), 0, 1).astype(np.float32)
            dry = np.cos(mix * np.pi / 2)[:, None]
            wet = np.sin(mix * np.pi / 2)[:, None]
            audio = audio * dry + other * wet
            heard += got_b
            got = max(got, got_b)

        dry_for_meter = audio
        seconds = fade_in if target >= fade else fade_out
        envelope, fade = self._envelope(frames, fade, target, seconds)
        audio = audio * (envelope[:, None] * np.float32(volume))
        np.clip(audio, -1.0, 1.0, out=audio)
        outdata[:] = audio

        playhead += got
        self._stash_meter(dry_for_meter)

        finished = False
        if duration_n and playhead >= duration_n:
            finished = True
        if slot.eof and slot.pending is None and slot.ring.count == 0 and got == 0:
            finished = True

        advanced = False
        send_ended = False
        with self._state:
            if self._slot is slot and not self._hold:
                self.playhead = playhead
                self.fade = fade
                self._xfade_heard = heard
                if pause_when_faded and fade <= 0.001:
                    self.playing = False
                    self._pause_when_faded = False
                if finished and self._next is not None and self._slot is slot:
                    new_duration = self._next.duration
                    self._retire.put(slot)
                    self._slot = self._next
                    self._next = None
                    self.playhead = heard
                    self.duration = new_duration
                    self._xfade_heard = 0
                    self._ended_sent = False
                    advanced = True
                elif finished and not self._ended_sent:
                    self._ended_sent = True
                    self.playing = False
                    send_ended = True
        if advanced:
            self.messages.put(("advanced",))
        elif send_ended:
            self.messages.put(("ended",))

    @staticmethod
    def _replay_gain(slot: _Slot, enabled: bool, preamp: float) -> float:
        if not enabled:
            return 1.0
        decibels = float(slot.replaygain_db or 0) + preamp
        if abs(decibels) < 0.05:
            return 1.0
        return float(10 ** (decibels / 20))

    def _envelope(self, frames: int, fade: float, target: float, seconds: float):
        if seconds <= 0.001 or abs(fade - target) < 1e-4:
            return np.full(frames, target, dtype=np.float32), target
        step = 1.0 / (seconds * self.sample_rate)
        direction = 1.0 if target > fade else -1.0
        ramp = fade + direction * step * np.arange(1, frames + 1, dtype=np.float32)
        if direction > 0:
            ramp = np.minimum(ramp, np.float32(target))
        else:
            ramp = np.maximum(ramp, np.float32(target))
        return ramp, float(ramp[-1])

    def _stash_meter(self, audio: np.ndarray) -> None:
        count = min(len(audio), self._meter.shape[0])
        if count <= 0:
            return
        with self._meter_lock:
            self._meter[:count] = audio[:count]
            self._meter_n = count
        level = float(np.max(np.abs(audio)))
        with self._state:
            self.level = min(1.0, self.level * 0.55 + min(1.0, level) * 0.45)
