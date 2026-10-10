"""The camera's video over FaceWatch's own link, handed to go2rtc as plain H.265 on a local port.

go2rtc's own Xiaomi link drops every ~12 s (go2rtc #2057), with a few seconds of broken pictures after each drop.
FaceWatch's link doesn't (see ptz.Link), and go2rtc serves the phones, clips and face detection from it as before."""
import logging
import socket
import struct
import threading
import time

from micloud import MiCloudError
from ptz import MotorError, decode, open_link

log = logging.getLogger("facewatch.camera_link")

H264, H265 = 4, 5


def keyframe_start(frame, codec):
    """Where a keyframe's parameter sets (H.265 VPS, H.264 SPS) begin in this frame, or -1."""
    wanted = 32 if codec == H265 else 7
    i = frame.find(b"\x00\x00\x01")
    while 0 <= i < min(1024, len(frame) - 3):
        kind = (frame[i + 3] >> 1) & 0x3F if codec == H265 else frame[i + 3] & 0x1F
        if kind == wanted:
            return i - 1 if i and frame[i - 1] == 0 else i
        i = frame.find(b"\x00\x00\x01", i + 3)
    return -1


class VideoLink:
    """Serves the video on 127.0.0.1:PORT, which go2rtc reads as a "tcp://" source. Each connection starts with the
    latest keyframe and the frames since, so it shows a picture at once."""

    PORT = 1986
    STALL_SECONDS = 8  # no video for this long: the link is opened again
    MAX_GOP = 200

    def __init__(self, mi, quality=3, port=PORT):
        self.mi, self.quality, self.port = mi, quality, port
        self.source = f"tcp://127.0.0.1:{port}"
        self.lock = threading.Lock()
        self.link = None
        self.gop = []  # frames since the last keyframe
        self.clients, self.waiting = [], []  # go2rtc connections; waiting ones start at the next keyframe
        self.last_frame = 0.0
        self.frames = 0
        self.running = False
        self.server = None

    def start(self, wait=12):
        """True once video is coming within wait seconds (go2rtc's connection can wait here for the first keyframe)."""
        self.running = True
        self.server = socket.create_server(("127.0.0.1", self.port))
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()
        deadline = time.time() + wait
        while time.time() < deadline and self.running and not self.frames:
            time.sleep(0.05)
        return bool(self.frames)

    def stop(self):
        self.running = False
        with self.lock:
            for conn in self.clients + self.waiting + [self.server]:
                try:
                    conn.close()
                except (OSError, AttributeError):
                    pass
            self.clients, self.waiting, self.gop = [], [], []
        if self.link is not None:
            self.link.close()

    def _run(self):
        delay, failing = 1, False
        while self.running:
            try:
                link = open_link(self.mi, on_media=self._media)
            except (MotorError, MiCloudError, OSError, KeyError, ValueError) as e:
                if not failing:
                    log.warning("Couldn't open the camera's video link (trying again): %s", e)
                failing = True
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            with self.lock:
                self.link, self.last_frame = link, time.time()
                self.gop = []  # nothing goes out before this link's first keyframe, or the pictures would break
            try:
                link.start_video(self.quality)
                if failing:
                    log.info("The camera's video link is back")
                failing, delay = False, 1
                while self.running and not link.closed and time.time() - self.last_frame < self.STALL_SECONDS:
                    time.sleep(0.5)
                if self.running:
                    log.warning("The camera's video stopped; opening its link again")
            except OSError:
                pass
            finally:
                link.close()

    def _media(self, link, item):
        """A packet: a 32-byte header, then the encrypted frame."""
        codec = struct.unpack_from("<I", item, 4)[0]
        if codec not in (H264, H265) or link is not self.link:
            return
        frame = decode(item[32:], link.key)
        start = keyframe_start(frame, codec)
        self.last_frame = time.time()
        self.frames += 1
        with self.lock:
            if start >= 0:
                frame = frame[start:]
                self.gop = [frame]
                self.clients += self.waiting
                self.waiting = []
            elif not self.gop:
                return
            elif len(self.gop) < self.MAX_GOP:
                self.gop.append(frame)
            for conn in list(self.clients):
                try:
                    conn.sendall(frame)
                except OSError:
                    self.clients.remove(conn)
                    conn.close()

    def _accept(self):
        while self.running:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            conn.settimeout(2)
            with self.lock:
                try:
                    for frame in self.gop:
                        conn.sendall(frame)
                except OSError:
                    conn.close()
                    continue
                (self.clients if self.gop else self.waiting).append(conn)
