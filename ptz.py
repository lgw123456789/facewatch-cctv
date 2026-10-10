"""FaceWatch's own link to a Xiaomi camera (MISS commands over CS2, as go2rtc's pkg/xiaomi/miss), and turning the camera:
the arrows, Origin and Follow faces. The link's keys come from Xiaomi's cloud, with the login saved in go2rtc.yaml."""
import json
import logging
import os
import queue
import socket
import struct
import threading
import time

import cv2
import numpy as np
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from facewatch import ViewMatcher
from micloud import MiCloudError

log = logging.getLogger("facewatch.ptz")

DIRECTIONS = {"left": 1, "right": 2, "up": 3, "down": 4}
MOVES = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
STEP_SECONDS = 0.4  # faster steps pile up in the camera and overshoot
HOLD_SECONDS = 1.2  # a held arrow keeps turning this long after the app's last "still holding"
# Measured on the C301: a step shows in the video ~0.45 s after it's sent and the picture is still by ~0.75 s; it moves
# the picture by these shares of its width and height.
SETTLE_SECONDS = 1.0
STEP_SIZE = (0.094, 0.139)
SEARCH_STEPS = 10  # how far Origin looks to each side when the step count is off
FOLLOW_RETURN_SECONDS = 10
FOLLOW_LIMIT = (12, 5)  # steps from the origin (sideways, up/down)
MANUAL_PAUSE_SECONDS = 20  # nothing turns the camera by itself this soon after someone used the arrows

CS2_PORT = 32108
MAGIC, MAGIC_DRW, MAGIC_TCP = 0xF1, 0xD1, 0x68
LAN_SEARCH, PUNCH, READY_TCP, DRW, PING, PONG = 0x30, 0x41, 0x43, 0xD0, 0xE0, 0xE1
CMD_AUTH, CMD_VIDEO_START, CMD_MOTOR, CMD_MOTOR_REPLY, CMD_ENCODED = 0x100, 0x102, 0x112, 0x113, 0x1001
CS2_VENDOR = 4


class MotorError(Exception):
    pass


def _hsalsa20(key, nonce):
    def rotl(v, n):
        return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF

    c, k, n = struct.unpack("<4I", b"expand 32-byte k"), struct.unpack("<8I", key), struct.unpack("<4I", nonce)
    x = [c[0], *k[:4], c[1], *n, c[2], *k[4:], c[3]]
    for _ in range(10):
        for a, b, d, e in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11),
                           (0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
            x[b] ^= rotl((x[a] + x[e]) & 0xFFFFFFFF, 7)
            x[d] ^= rotl((x[b] + x[a]) & 0xFFFFFFFF, 9)
            x[e] ^= rotl((x[d] + x[b]) & 0xFFFFFFFF, 13)
            x[a] ^= rotl((x[e] + x[d]) & 0xFFFFFFFF, 18)
    return struct.pack("<8I", *(x[i] for i in (0, 5, 10, 15, 6, 7, 8, 9)))


def shared_key(private, device_public):
    """NaCl's box key (X25519, then HSalsa20)."""
    return _hsalsa20(private.exchange(X25519PublicKey.from_public_bytes(device_public)), bytes(16))


def _chacha20(key, nonce8, data):
    # Counter 0, then a 12-byte nonce: 4 zero bytes and the message's 8.
    return Cipher(algorithms.ChaCha20(key, bytes(8) + nonce8), mode=None).encryptor().update(data)


def encode(data, key):
    nonce8 = os.urandom(8)
    return nonce8 + _chacha20(key, nonce8, data)


def decode(data, key):
    return _chacha20(key, data[:8], data[8:])


def _handshake(ip, deadline):
    """Finds the camera over UDP; it answers with the TCP port to use."""
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(0.5)
    try:
        message, port = bytes([MAGIC, LAN_SEARCH, 0, 0]), CS2_PORT
        for wanted in (PUNCH, READY_TCP):
            while True:
                if time.time() > deadline:
                    raise MotorError("The camera didn't answer on the home network. Is the laptop on the same WiFi?")
                try:
                    udp.sendto(message, (ip, port))
                    reply, (sender, sender_port) = udp.recvfrom(1500)
                except socket.timeout:
                    continue
                except OSError:  # Windows reports "port unreachable" as a reset
                    time.sleep(0.3)
                    continue
                if sender == ip and len(reply) >= 16 and reply[1] == wanted:
                    message, port = reply, sender_port  # the punch packet goes back where it came from
                    break
        return port
    finally:
        udp.close()


class Link:
    """A logged-in CS2 link over TCP. on_media(link, packet) gets the video packets after start_video()."""

    def __init__(self, ip, public_key, sign, key, timeout=6, on_media=None):
        self.key, self.on_media = key, on_media
        self.lock = threading.Lock()
        self.seq = 0
        self.replies = queue.Queue()
        self.closed = False
        deadline = time.time() + timeout
        port = _handshake(ip, deadline)
        try:
            self.sock = socket.create_connection((ip, port), timeout=max(1.0, deadline - time.time()))
        except OSError as e:
            raise MotorError(f"Couldn't connect to the camera ({e}).") from e
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._keep_alive, daemon=True).start()
        login = json.dumps({"public_key": public_key, "sign": sign, "uuid": "", "support_encrypt": 0},
                           separators=(",", ":"))
        try:
            self._command(CMD_AUTH, login.encode())
            reply = self.replies.get(timeout=max(1.0, deadline - time.time()))
        except (OSError, queue.Empty):
            reply = b""
        if b'"result":"success"' not in reply:
            self.close()
            raise MotorError(f"The camera didn't accept the login{' (no answer)' if not reply else ''}. "
                             "Try again in a minute.")

    def _send(self, message):
        self.sock.sendall(struct.pack(">HB5x", len(message), MAGIC_TCP) + message)  # TCP adds an 8-byte header

    def _command(self, cmd, payload):
        with self.lock:
            self._send(struct.pack(">BBHBBHII", MAGIC, DRW, 12 + len(payload), MAGIC_DRW, 0, self.seq,
                                   4 + len(payload), cmd) + payload)
            self.seq = (self.seq + 1) & 0xFFFF

    def _encoded(self, cmd, data):
        payload = struct.pack(">I", cmd) + json.dumps(data, separators=(",", ":")).encode()
        self._command(CMD_ENCODED, encode(payload, self.key))

    def motor(self, operation, wait):
        """Sends one step and waits up to wait seconds for the camera's answer. True if it answered."""
        while not self.replies.empty():
            self.replies.get_nowait()
        self._encoded(CMD_MOTOR, {"operation": operation})
        end = time.time() + wait
        while (left := end - time.time()) > 0:
            try:
                reply = self.replies.get(timeout=left)
            except queue.Empty:
                break
            if (struct.unpack(">I", reply[:4])[0] == CMD_ENCODED and len(reply) >= 16
                    and struct.unpack(">I", decode(reply[4:], self.key)[:4])[0] == CMD_MOTOR_REPLY):
                return True
        return False

    def start_video(self, quality=3):
        """Asks for the video without audio (quality 3 is the C301's 2K)."""
        self._encoded(CMD_VIDEO_START, {"videoquality": quality, "enableaudio": 0})

    def _read(self):
        # Everything is read as it comes, channel 0 (replies, the camera's own messages) and 2 (video). go2rtc leaves
        # channel 0 unread, which is why the camera drops its link every ~12 s (go2rtc #2057).
        pending = {0: b"", 2: b""}
        try:
            self.sock.settimeout(None)
            reader = self.sock.makefile("rb")
            while len(head := reader.read(8)) == 8:
                message = reader.read(struct.unpack(">H", head[:2])[0])
                if message[1] == PING:
                    with self.lock:
                        self._send(bytes([MAGIC, PONG, 0, 0]))
                elif message[1] == DRW and message[5] in pending:
                    channel = message[5]
                    data = pending[channel] + message[8:]
                    while len(data) >= 4 and len(data) - 4 >= (size := struct.unpack(">I", data[:4])[0]):
                        item, data = data[4:4 + size], data[4 + size:]
                        if channel == 2:
                            if self.on_media:
                                self.on_media(self, item)
                        else:
                            if self.replies.qsize() > 50:  # the camera's own messages, which nobody waits for
                                self.replies.get_nowait()
                            self.replies.put(item)
                    pending[channel] = data
        except (OSError, ValueError, IndexError, struct.error, queue.Empty):
            pass
        self.closed = True

    def _keep_alive(self):
        while not self.closed:
            time.sleep(1)
            try:
                with self.lock:
                    self._send(bytes([MAGIC, PING, 0, 0]))
            except OSError:
                self.closed = True

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


def open_link(mi, on_media=None):
    """A new logged-in Link (about two seconds)."""
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    info = mi.miss_vendor(public.hex())
    if (info.get("vendor") or {}).get("vendor") != CS2_VENDOR:
        raise MotorError("This camera uses a kind of link FaceWatch can't open.")
    ip = socket.gethostbyname(mi.camera()[5])
    return Link(ip, public.hex(), info["sign"], shared_key(private, bytes.fromhex(info["public_key"])), on_media=on_media)


class Motor:
    """Turns the camera one step at a time. The position is counted in steps from the origin; Origin goes back by the
    count, then lines the picture up with the saved origin view."""

    def __init__(self, mi, folder):
        self.mi = mi
        self.position_file, self.origin_file = folder / "ptz.json", folder / "origin.jpg"
        self.lock = threading.Lock()  # one step at a time
        self.link = None  # its own, used when the video's isn't open
        self.shared = None  # set by the app: gives the video's open link
        self.last = 0.0  # when the last step was sent
        self.action = 0  # each request takes a new number, which stops whatever was running
        self.holding = None  # (direction, action number, until)
        self.answers = None  # whether the camera answers steps (unknown until the first)
        self.used = 0.0  # when someone last used the arrows or Origin
        self.returning = False
        self.view = ViewMatcher()
        self.origin = None  # (file time, features of the origin picture)
        self._available = None
        try:
            saved = json.loads(self.position_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self.position = saved.get("position", [0, 0])
        self.flip = saved.get("flip", [1, 1])  # -1 where the picture moves the other way (camera hung upside down)

    def available(self):
        """Whether the camera comes through a Xiaomi login in go2rtc.yaml."""
        if self._available is None:
            try:
                self._available = bool(self.mi.camera())
            except MiCloudError:
                self._available = False
        return self._available

    def _ready_link(self):
        """The video's link if it's open, otherwise its own (opened if needed). Call with self.lock held."""
        shared = self.shared() if self.shared else None
        if shared is not None and not shared.closed:
            return shared
        if self.link is None or self.link.closed:
            self.link = None
            self.link = open_link(self.mi)
        return self.link

    def close(self):
        with self.lock:
            if self.link is not None:
                self.link.close()
                self.link = None

    def _step(self, direction, action):
        """One step for that request, unless a newer one has taken over. Raises MotorError."""
        with self.lock:
            time.sleep(max(0.0, self.last + STEP_SECONDS - time.time()))
            if action != self.action:
                return False
            for attempt in (1, 2):
                try:
                    # Waiting for the camera's answer keeps steps from piling up; one that never answers is paced by time.
                    wait = 0.0 if self.answers is False else 1.0
                    answered = self._ready_link().motor(DIRECTIONS[direction], wait)
                    if wait:
                        self.answers = answered
                    break
                except (OSError, KeyError, ValueError) as e:
                    if self.link is not None:
                        self.link.close()
                        self.link = None
                    if attempt == 2:
                        raise MotorError(f"Couldn't send the turn to the camera ({type(e).__name__}).") from e
            self.last = time.time()
            dx, dy = MOVES[direction]
            self.position = [self.position[0] + dx, self.position[1] + dy]
            self._save_position()
            return True

    def _save_position(self):
        try:
            self.position_file.parent.mkdir(parents=True, exist_ok=True)
            self.position_file.write_text(json.dumps({"position": self.position, "flip": self.flip}), encoding="utf-8")
        except OSError:
            pass

    def _new_action(self):
        self.action += 1
        self.holding = None
        return self.action

    def busy(self):
        return self.holding is not None or self.returning

    def hold(self, direction):
        """Turns one step now, and keeps turning while hold() is called again within HOLD_SECONDS."""
        self.used = time.time()
        holding = self.holding
        if holding and holding[0] == direction and holding[1] == self.action and time.time() < holding[2]:
            self.holding = (direction, holding[1], time.time() + HOLD_SECONDS)
            return
        action = self._new_action()
        self.holding = (direction, action, time.time() + HOLD_SECONDS)
        try:
            self._step(direction, action)  # the first step here, so a problem reaches the app
        except MotorError:
            self.holding = None
            raise
        threading.Thread(target=self._keep_turning, args=(action,), daemon=True).start()

    def _keep_turning(self, action):
        while (holding := self.holding) and holding[1] == action and time.time() <= holding[2]:
            try:
                if not self._step(holding[0], action):
                    return
            except MotorError as e:
                log.warning("Stopped turning: %s", e)
                return

    def stop(self):
        """Stops turning, and a return to the origin, at once."""
        self.used = time.time()
        self._new_action()

    def nudge(self, direction):
        """One step for Follow faces (not counted as someone using the arrows)."""
        return self._step(direction, self._new_action())

    def has_origin(self):
        return self.origin_file.exists()

    def set_origin(self, frame):
        self.used = time.time()
        self._new_action()
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (1280, round(h * 1280 / w)), interpolation=cv2.INTER_AREA) if w > 1280 else frame
        ok, data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise MotorError("Couldn't save the origin picture.")
        self.origin_file.parent.mkdir(parents=True, exist_ok=True)
        self.origin_file.write_bytes(data.tobytes())
        with self.lock:
            self.position = [0, 0]
            self._save_position()

    def _origin_view(self):
        if not self.origin_file.exists():
            return None
        stamp = self.origin_file.stat().st_mtime
        if self.origin is None or self.origin[0] != stamp:
            image = cv2.imdecode(np.fromfile(str(self.origin_file), np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                return None
            self.origin = (stamp, self.view.features(image))
        return self.origin[1]

    def go_to_origin(self, newest_frame, manual=True):
        """Turns back to the origin and says what happened. newest_frame() gives the camera's newest picture, or None
        while it's off (then only the count is used)."""
        if manual:
            self.used = time.time()
        action = self._new_action()
        origin = self._origin_view()
        if origin is None:
            raise MotorError("There's no origin yet. Turn the camera where you want it and tap Set as origin.")
        self.returning = True
        try:
            return self._return(action, origin, newest_frame)
        finally:
            self.returning = False

    def _return(self, action, origin, newest_frame):
        pan, tilt = self.position
        for direction, count in (("left" if pan > 0 else "right", abs(pan)), ("up" if tilt > 0 else "down", abs(tilt))):
            for _ in range(count):
                if not self._step(direction, action):
                    return "Stopped."
        if newest_frame() is None:
            return "Back at the origin (by counting steps)."
        # Then line the picture up a step at a time, learning a step's size and direction as it goes.
        size = [STEP_SIZE[0] * ViewMatcher.WIDTH, STEP_SIZE[1] * ViewMatcher.WIDTH * 9 / 16]
        sign, before = list(self.flip), None
        for _ in range(16):
            time.sleep(SETTLE_SECONDS)
            if action != self.action:
                return "Stopped."
            frame = newest_frame()
            offset = self.view.offset(origin, frame) if frame is not None else None
            if offset is None:
                if before is not None:
                    return ("Back near the origin, but the picture couldn't be matched to check it (too dark, or the "
                            "view has changed). Set the origin again if it's off.")
                found = self._search(action, origin, newest_frame)
                if found is None:
                    return "Stopped."
                if not found:
                    return ("Couldn't find the origin's view nearby (very dark, or the view has changed). Turn the "
                            "camera back and tap Set this view as the origin.")
                continue
            if before:
                axis, error = before
                moved = offset[axis] - error
                if abs(moved) > 5:
                    size[axis] = min(200.0, max(15.0, abs(moved)))
                if moved * error > 0:  # it moved the wrong way: the picture is flipped
                    sign[axis] = self.flip[axis] = -sign[axis]
            axis = 0 if abs(offset[0]) / size[0] >= abs(offset[1]) / size[1] else 1
            if abs(offset[axis]) <= 0.6 * size[axis]:
                with self.lock:
                    self.position = [0, 0]
                    self._save_position()
                return "Back at the origin."
            before = (axis, offset[axis])
            forward = offset[axis] * sign[axis] > 0
            direction = ("right" if forward else "left") if axis == 0 else ("down" if forward else "up")
            if not self._step(direction, action):
                return "Stopped."
        return "Nearly back at the origin."

    def _search(self, action, origin, newest_frame):
        """Looks sideways for the origin's view, two steps at a time: left, then across to the right. The count is off
        when something else turned the camera (it centres itself when it restarts). None if stopped."""
        for direction, checks in (("left", SEARCH_STEPS // 2), ("right", SEARCH_STEPS)):
            for _ in range(checks):
                for _ in range(2):
                    if not self._step(direction, action):
                        return None
                time.sleep(SETTLE_SECONDS)
                frame = newest_frame()
                if action != self.action:
                    return None
                if frame is not None and self.view.offset(origin, frame) is not None:
                    return True
        for _ in range(SEARCH_STEPS):  # back to where it started
            if not self._step("left", action):
                return None
        return False


class Autopilot:
    """Turns the camera by itself: towards faces (Follow faces), and back to the origin a little after the last
    followed face has gone, or origin_return_minutes after someone used the arrows."""

    def __init__(self, motor):
        self.motor = motor
        self.followed = False  # Follow faces moved the camera since it was last at the origin
        self.last_seen = 0.0
        self.retry_after = 0.0

    def tick(self, now, cfg, targets, seen_at, frame_size, newest_frame):
        """targets: (x, y, w, h, is someone known) of each face, or of where a hidden face would be, in the picture the
        watcher processed at seen_at."""
        motor = self.motor
        if motor.busy() or now - motor.used < MANUAL_PAUSE_SECONDS or now < self.retry_after:
            return
        wanted = [t for t in targets if cfg["follow_known"] or not t[4]] if cfg["follow_faces"] else []
        if wanted and frame_size:
            self.last_seen = now
            if seen_at > motor.last + SETTLE_SECONDS:  # the picture shows where the last step left it
                direction, steps = self._aim(max(wanted, key=lambda t: t[2] * t[3]), frame_size)
                for _ in range(steps):
                    if not self._turn(lambda: motor.nudge(direction), now):
                        break
                    self.followed = True
            return
        if motor.position == [0, 0] or not motor.has_origin():
            self.followed = False
            return
        minutes = cfg["origin_return_minutes"]
        if ((self.followed and now - self.last_seen > FOLLOW_RETURN_SECONDS)
                or (minutes and now - max(motor.used, self.last_seen) > minutes * 60)):
            message = self._turn(lambda: motor.go_to_origin(newest_frame, manual=False), now)
            if message:
                log.info("Camera turned back to its origin by itself: %s", message)
                self.followed = False

    def _aim(self, target, frame_size):
        """(direction, steps) towards the target: up to 3 steps when it's far off, without passing the middle."""
        x, y, w, h, _ = target
        dx = (x + w / 2) / frame_size[0] - 0.5
        dy = (y + h / 2) / frame_size[1] - 0.5
        over_x, over_y = abs(dx) / 0.15, abs(dy) / 0.2  # near enough within these shares of the picture
        if max(over_x, over_y) <= 1:
            return None, 0
        if over_x >= over_y:
            direction, axis, off = ("right" if dx * self.motor.flip[0] > 0 else "left"), 0, abs(dx)
        else:
            direction, axis, off = ("down" if dy * self.motor.flip[1] > 0 else "up"), 1, abs(dy)
        room = FOLLOW_LIMIT[axis] - self.motor.position[axis] * MOVES[direction][axis]
        steps = min(max(1, min(3, int((off - 0.05) / STEP_SIZE[axis]))), room)
        return (direction, steps) if steps > 0 else (None, 0)

    def _turn(self, move, now):
        try:
            return move()
        except (MotorError, MiCloudError, OSError) as e:
            log.warning("Couldn't turn the camera by itself: %s", e)
            self.retry_after = now + 120
            return None
