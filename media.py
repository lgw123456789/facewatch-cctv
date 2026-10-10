"""Alert clips (cut from the camera's own video, nothing re-encoded), the phones' Live feed, and the alarm and Talk on
the camera's speaker through go2rtc."""
import asyncio
import collections
import json
import logging
import os
import shutil
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np
import requests
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

log = logging.getLogger("facewatch.media")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ALARM_WORDS = "Warning. You are being recorded. The owner has been alerted."


def find_ffmpeg():
    """ffmpeg on PATH, or where winget puts it (programs started before the install don't see it on PATH)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    return next((str(p) for p in sorted(packages.glob("*FFmpeg*/*/bin/ffmpeg.exe"))), None)


def child(data, start, end, kind):
    """(start, end) of the first box of this type inside data[start:end] of an MP4, or None."""
    while start + 8 <= end:
        size, name = struct.unpack_from(">I4s", data, start)
        if size < 8:
            return None
        if name == kind:
            return start, start + size
        start += size
    return None


def fragment_info(fragment):
    """(decode time, tfdt position, is keyframe) of a moof + mdat pair (go2rtc writes one frame each)."""
    traf = child(fragment, 8, struct.unpack_from(">I", fragment)[0], b"traf")
    tfhd = child(fragment, traf[0] + 8, traf[1], b"tfhd")
    tfdt = child(fragment, traf[0] + 8, traf[1], b"tfdt")
    trun = child(fragment, traf[0] + 8, traf[1], b"trun")
    flags, pos, sample_flags = int.from_bytes(fragment[tfhd[0] + 9:tfhd[0] + 12], "big"), tfhd[0] + 16, 0
    for bit, size in ((0x01, 8), (0x02, 4), (0x08, 4), (0x10, 4)):
        pos += size if flags & bit else 0
    if flags & 0x20:
        sample_flags = struct.unpack_from(">I", fragment, pos)[0]
    if trun and fragment[trun[0] + 11] & 0x04:  # first-sample-flags override the default
        offset = 4 if fragment[trun[0] + 11] & 0x01 else 0
        sample_flags = struct.unpack_from(">I", fragment, trun[0] + 16 + offset)[0]
    fmt = ">Q" if fragment[tfdt[0] + 8] == 1 else ">I"
    return struct.unpack_from(fmt, fragment, tfdt[0] + 12)[0], (tfdt[0] + 12, fmt), not sample_flags & 0x10000


class ClipRecorder:
    """Keeps the last half minute of video for alert clips, and feeds Live from the latest keyframe so the picture
    shows at once."""

    KEEP_SECONDS = 30
    MAX_BEHIND = 200  # fragments (10 s) a phone may fall behind before it's dropped and starts afresh

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.lock = threading.Lock()
        self.init, self.moof, self.mime, self.ready = None, None, None, False
        self.parts = collections.deque()  # (time received, decode time, tfdt position, keyframe, moof + mdat)
        self.watchers = []  # [event loop, asyncio.Queue, started at a keyframe]
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False
        with self.lock:
            self._send(None)

    def watch(self, loop, codecs):
        """(MIME type, init segment, fragments since the latest keyframe, asyncio.Queue of the next ones ending with
        None) for a phone that can play codecs, or None."""
        with self.lock:
            if not self.ready or not self.mime or not any(c.strip()[:4] and c.strip()[:4] in self.mime for c in codecs):
                return None
            parts = list(self.parts)
            keys = [i for i, part in enumerate(parts) if part[3]]
            queue = asyncio.Queue()
            self.watchers.append([loop, queue, bool(keys)])
            return self.mime, self.init, [part[4] for part in parts[keys[-1]:]] if keys else [], queue

    def unwatch(self, queue):
        with self.lock:
            self.watchers = [w for w in self.watchers if w[1] is not queue]

    def _send(self, fragment, key=False):
        """Passes a fragment (None: the end) to the phones. Call with self.lock held."""
        for watcher in list(self.watchers):
            loop, queue, started = watcher
            if fragment is not None and not started:
                if not key:
                    continue  # nothing can be shown before a keyframe
                watcher[2] = True
            item = fragment
            if fragment is None or queue.qsize() > self.MAX_BEHIND:
                item = None
                self.watchers.remove(watcher)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # that phone has gone
                if watcher in self.watchers:
                    self.watchers.remove(watcher)

    def _run(self):
        while self.running:
            try:
                with connect(self.ws_url, max_size=None, open_timeout=10) as ws:
                    ws.send(json.dumps({"type": "mse", "value": "hvc1.1.6.L153.B0,avc1.640029"}))
                    buffer = b""
                    while self.running:
                        message = ws.recv(timeout=15)
                        if isinstance(message, str):
                            reply = json.loads(message)
                            if reply.get("type") == "mse":
                                self.mime = reply.get("value")
                            continue
                        buffer += message
                        while len(buffer) >= 8:
                            size = struct.unpack_from(">I", buffer)[0]
                            if size < 8:
                                raise ValueError("broken MP4 box")
                            if len(buffer) < size:
                                break
                            self._add(buffer[4:8], buffer[:size])
                            buffer = buffer[size:]
            except (OSError, WebSocketException, struct.error, TypeError, ValueError):
                pass
            with self.lock:
                self.init, self.moof, self.ready = None, None, False
                self.parts.clear()
                self._send(None)
            time.sleep(3)

    def _add(self, kind, box):
        now = time.time()
        with self.lock:
            if kind == b"ftyp":
                self.init, self.ready = box, False
                self.parts.clear()
                self._send(None)  # phones need the new init: they reconnect
            elif kind == b"moov":
                self.init += box
                self.ready = True
            elif kind == b"moof":
                self.moof = box
            elif kind == b"mdat" and self.moof:
                fragment, self.moof = self.moof + box, None
                part = (now, *fragment_info(fragment), fragment)
                self.parts.append(part)
                self._send(fragment, part[3])
                while now - self.parts[0][0] > self.KEEP_SECONDS:
                    self.parts.popleft()

    def clip(self, start, end):
        """The video from the last keyframe at or before start until end (time.time() values), as an MP4 starting at 0,
        or None."""
        with self.lock:
            init, parts = self.init, [p for p in self.parts if p[0] <= end]
        keys = [i for i, p in enumerate(parts) if p[3]]
        if not init or not keys:
            return None
        first = max((i for i in keys if parts[i][0] <= start), default=keys[0])
        base = parts[first][1]
        out = bytearray(init)
        for _, decode_time, (pos, fmt), _, fragment in parts[first:]:
            fragment = bytearray(fragment)
            struct.pack_into(fmt, fragment, pos, decode_time - base)
            out += fragment
        return bytes(out)

    def save(self, path, start, end, ffmpeg=None):
        """Writes the clip to path, as a plain MP4 if ffmpeg is there (more players, Telegram included, take it).
        False if there was no video."""
        data = self.clip(start, end)
        if data is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = path.with_name(path.stem + ".fmp4")
        raw.write_bytes(data)
        if ffmpeg:
            # Apple players only play H.265 tagged as hvc1.
            tag = ["-tag:v", "hvc1"] if b"hvcC" in data[:4096] else []
            try:
                done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-c", "copy", *tag,
                                       "-movflags", "+faststart", str(path)], timeout=60, creationflags=NO_WINDOW)
                if done.returncode == 0:
                    raw.unlink()
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
        raw.replace(path)
        return True


def make_alarm(path):
    """A siren and a spoken warning (Windows' own text-to-speech), as a WAV file."""
    rate = 16000
    voice = np.zeros(0, np.float32)
    spoken = path.with_name("alarm_voice.wav")
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$s.SetOutputToWaveFile('{0}', (New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
              "16000, 'Sixteen', 'Mono'))); $s.Speak('{1}'); $s.Dispose()").format(spoken, ALARM_WORDS)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=60,
                       capture_output=True, creationflags=NO_WINDOW)
        with wave.open(str(spoken)) as w:
            voice = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    except (OSError, subprocess.SubprocessError, wave.Error):
        log.warning("Windows text-to-speech isn't available, so the alarm is a siren only")
    finally:
        spoken.unlink(missing_ok=True)
    t = np.arange(rate * 5 // 2) / rate
    # The pitch sweeps between 600 and 1300 Hz twice a second.
    siren = 0.8 * np.sin(2 * np.pi * np.cumsum(950 + 350 * np.sin(2 * np.pi * 2 * t)) / rate)
    gap = np.zeros(rate // 4)
    sound = np.concatenate([siren, gap, voice, gap, siren, gap, voice])
    write_wav(path, sound, rate)


def write_wav(path, samples, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())


def wav_seconds(path):
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (OSError, EOFError, wave.Error):
        return 20.0


def sound_file(path):
    """A go2rtc source playing a sound file in the camera's format (Opus)."""
    return f"ffmpeg:{Path(path).as_posix()}#input=file#audio=opus"


class Speaker:
    """Plays the alarm or Talk on the camera's speaker through go2rtc, again after each go2rtc reconnect."""

    def __init__(self, api, stream):
        self.url = f"http://{api[0]}:{api[1]}/api/streams"
        self.stream = stream
        self.lock = threading.Lock()  # held around calls to go2rtc, so a replay can't land after a stop
        self.session = None  # (number, kind, end time, latest end time)
        self.count = 0

    def _play(self, source):
        try:
            r = requests.post(self.url, params={"dst": self.stream, "src": source}, timeout=10)
        except requests.RequestException as e:
            raise RuntimeError(f"go2rtc didn't answer ({type(e).__name__})") from e
        if not r.ok:
            raise RuntimeError(r.text.strip() or r.reason)

    def _silence(self):
        try:
            self._play("")  # an empty source stops what go2rtc is playing
        except RuntimeError as e:
            log.warning("Couldn't stop the camera's speaker: %s", e)

    def _link(self):
        """The id of go2rtc's link to the camera, which changes when it reconnects."""
        try:
            producers = requests.get(self.url, params={"src": self.stream}, timeout=5).json().get("producers")
            return (producers or [{}])[0].get("id")
        except (requests.RequestException, ValueError, AttributeError):
            return None

    def start(self, kind, source, seconds, limit=None):
        """Plays source for seconds, replacing what was playing; returns a number for extend() and stop(). extend() can't
        keep it going past limit seconds from now."""
        with self.lock:
            self.count += 1
            number, now = self.count, time.time()
            self.session = (number, kind, now + seconds, now + max(seconds, limit or 0))
            try:
                self._play(source)
            except RuntimeError:
                self.session = None
                self._silence()
                raise
        threading.Thread(target=self._keep, args=(number, source), daemon=True).start()
        return number

    def extend(self, number, seconds):
        """Keeps that session going for seconds more. False if it has ended."""
        with self.lock:
            session = self.session
            if not session or session[0] != number or time.time() > session[2]:
                return False
            self.session = (*session[:2], min(time.time() + seconds, session[3]), session[3])
            return True

    def _keep(self, number, source):
        link = self._link()
        while True:
            time.sleep(0.5)
            session = self.session
            if not session or session[0] != number:
                return
            if time.time() > session[2]:
                self.stop(number)
                return
            now = self._link()
            if now is None or now == link:
                continue
            link = now
            with self.lock:
                if self.session and self.session[0] == number:
                    try:
                        self._play(source)
                    except RuntimeError as e:
                        log.warning("Couldn't play on the camera again after it reconnected: %s", e)

    def stop(self, number=None):
        """Silences the speaker; with a number, only if that session is still playing."""
        with self.lock:
            if number is not None and (self.session is None or self.session[0] != number):
                return
            self.session = None
            self._silence()

    def playing(self, kind):
        session = self.session
        return bool(session) and session[1] == kind and time.time() <= session[2]
