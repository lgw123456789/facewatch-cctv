import argparse
import asyncio
import ctypes
import hashlib
import hmac
import importlib
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

# FastAPI loads ujson/orjson if installed, and fails if Smart App Control blocks them (it only allows them missing).
# FaceWatch doesn't need them, so a blocked one counts as missing.
for _optional in ("ujson", "orjson"):
    try:
        importlib.import_module(_optional)
    except ImportError:
        sys.modules[_optional] = None

import cv2
import numpy as np
import uvicorn
import websockets
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import camera_link
import facewatch as fw
import media
import micloud
import ptz

# Windows can map these to the wrong types, which stops phones from installing the app.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")

WEB_DIR = fw.ROOT / "web"
APP_DATA_DIR = fw.ROOT / "app_data"
GO2RTC_EXE = fw.ROOT / "go2rtc.exe"
GO2RTC_API = ("127.0.0.1", 1984)
GO2RTC_STREAM_RE = re.compile(r"^rtsp://(?:127\.0\.0\.1|localhost):8554/")
COOKIE = "facewatch_session"
SESSION_SECONDS = 30 * 24 * 3600
LIVE_WIDTH = 960
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
PERSON_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 ._-]{0,38}[A-Za-z0-9])?$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PHOTO_RE = re.compile(r"^[A-Za-z0-9 ._-]+\.(?:jpe?g|png|bmp|webp)$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SNAPSHOT_RE = re.compile(r"^\d{6}\.jpg$")
CLIP_RE = re.compile(r"^\d{6}\.mp4$")
ALARM_SOUND = APP_DATA_DIR / "alarm.wav"
LINK_RETRY_SECONDS = 60  # how often FaceWatch's own camera link is tried again while go2rtc's is used
TALK_STREAM = "talk"  # the empty go2rtc stream in go2rtc.yaml that the phone's microphone is sent to
TALK_CHECK_IN = 6  # Talk stops this many seconds after the phone stops checking in (it does every 2 s)
TALK_LIMIT = 5 * 60

# Settings the app may change: (bool, str, or a (min, max) number range, the label the app shows).
SETTINGS = {
    "camera_name": (str, "Camera name"),
    "camera_autostart": (bool, "Turn on when FaceWatch starts"),
    "notify_known": (bool, "People I know arriving"),
    "notify_unknown": (bool, "Unknown people"),
    "unknown_alert_after_seconds": ((1, 600), "Alert after"),
    "unknown_grace_seconds": ((0, 60), "Allowed gap"),
    "unknown_cooldown_seconds": ((0, 86400), "Repeat at most every"),
    "notify_hidden": (bool, "Someone hiding their face"),
    "hidden_alert_after_seconds": ((5, 600), "Face-hidden alert after"),
    "hidden_cooldown_seconds": ((0, 86400), "Face-hidden repeat"),
    "notify_offline": (bool, "Camera goes offline"),
    "offline_alert_after_seconds": ((30, 3600), "Offline alert after"),
    "notify_zones": (bool, "Zone warnings"),
    "zone_alert_after_seconds": ((0, 60), "Zone warning after"),
    "zone_cooldown_seconds": ((0, 86400), "Zone warning repeat"),
    "entrance_messages": ((1, 10), "Entrance messages"),
    "inside_messages": ((1, 10), "Inside messages"),
    "cooldown_seconds": ((0, 86400), "Save again at most every"),
    "match_threshold": ((0.2, 0.8), "Match strictness"),
    "keep_alert_days": ((0, 3650), "Keep alerts for"),
    "clip_seconds": ((0, 30), "Clip length"),
    "camera_speaker": (bool, "Camera speaker"),
    "camera_control": (bool, "Camera arrows"),
    "own_camera_link": (bool, "Steady video link"),
    "follow_faces": (bool, "Follow faces"),
    "follow_known": (bool, "Also follow people I know"),
    "origin_return_minutes": ((0, 120), "Back to origin after"),
    "home_mode": (bool, "Home mode"),
    "daily_summary": (bool, "Daily summary"),
    "summary_hour": ((0, 23), "Summary time"),
    "alarm_inside": (bool, "Alarm when someone unknown is inside"),
    "alarm_volume": ((0, 100), "Alarm volume"),
    "talk_volume": ((0, 100), "Talk volume"),
}

log = logging.getLogger("facewatch.server")
CODE_FILES = [fw.ROOT / name for name in ("server.py", "facewatch.py", "ptz.py", "camera_link.py", "media.py", "micloud.py")]


def code_stamp():
    return max((f.stat().st_mtime for f in CODE_FILES if f.exists()), default=0)


STARTED_CODE = code_stamp()


def code_changed():
    """Whether the code changed since FaceWatch started (the app's pages are always read fresh)."""
    return code_stamp() != STARTED_CODE


ctx = SimpleNamespace(cfg=None, config_path=None, camera=None, accounts=None,
                      mi=micloud.MiCloud(fw.ROOT / "go2rtc.yaml"))
ctx.motor = ptz.Motor(ctx.mi, APP_DATA_DIR)


def shared_camera_link():
    video = ctx.camera.video_link if ctx.camera is not None else None
    return video.link if video is not None else None


ctx.motor.shared = shared_camera_link
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def port_open(address):
    try:
        with socket.create_connection(address, timeout=0.5):
            return True
    except OSError:
        return False


class JobLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32),
                ("IoCounters", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def end_with_facewatch(process):
    """Has Windows end the process with FaceWatch, even when its window is just closed (else go2rtc keeps running
    with its old settings)."""
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    job = kernel32.CreateJobObjectW(None, None)
    limits = JobLimits(LimitFlags=0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: ends it when FaceWatch exits
    if not (job and kernel32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(limits),
                                                     ctypes.sizeof(limits))
            and kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(int(process._handle)))):
        log.warning("Couldn't tie go2rtc to FaceWatch; it may keep running after FaceWatch closes")


class Camera:
    """Turns go2rtc and face recognition on and off. The face models stay loaded, so adding people works while the
    camera is off."""

    def __init__(self, cfg, source, telegram):
        self.cfg, self.source, self.telegram = cfg, source, telegram
        self.state, self.message = "off", "Camera is off"
        self.lock = threading.Lock()
        self.models_lock = threading.Lock()
        self.watcher = None
        self.go2rtc = None
        self.go2rtc_log = None
        self.clips = None
        self.speaker = None
        self.video_link = None

    @property
    def stream(self):
        """The go2rtc stream name when the camera comes through go2rtc (phones can then play its own video)."""
        if isinstance(self.source, str) and GO2RTC_STREAM_RE.match(self.source):
            return self.source.rsplit("/", 1)[-1]
        return None

    def stream_url(self, name):
        """The RTSP address of another go2rtc stream, e.g. the talk stream."""
        return f"{self.source.rsplit('/', 1)[0]}/{name}"

    def models(self):
        """The FaceWatch object, loading the face models the first time (takes a few seconds)."""
        with self.models_lock:
            if self.watcher is None:
                self.watcher = fw.FaceWatch(self.cfg, self.telegram)
            return self.watcher

    def start(self):
        with self.lock:
            if self.state in ("starting", "on"):
                return
            self.state, self.message = "starting", "Starting…"
        threading.Thread(target=self._start, daemon=True).start()

    def _progress(self, message):
        with self.lock:
            if self.state == "starting":
                self.message = message

    def _start(self):
        try:
            if self.stream:
                self._progress("Connecting to the camera…")
                self._start_video_link()
                self._progress("Starting go2rtc…")
                self._start_go2rtc()
            self._progress("Loading face recognition…")
            watcher = self.models()
            with self.lock:
                if self.state != "starting":
                    self._stop_go2rtc()  # turned off while it was starting
                    self._stop_video_link()
                    return
                watcher.on_alert = on_alert
                watcher.start(self.source)
                if self.stream:
                    self.clips = media.ClipRecorder(f"ws://{GO2RTC_API[0]}:{GO2RTC_API[1]}/api/ws?src={self.stream}")
                    self.speaker = media.Speaker(GO2RTC_API, self.stream)
                self.state, self.message = "on", "Camera is on"
                if self.stream and ctx.motor.available() and not ctx.motor.has_origin():
                    threading.Thread(target=save_first_origin, daemon=True).start()
                if self.go2rtc is not None:
                    threading.Thread(target=self._keep_go2rtc, args=(self.go2rtc,), daemon=True).start()
        except (Exception, SystemExit) as e:
            log.exception("Could not start the camera")
            with self.lock:
                self._stop_go2rtc()
                self._stop_video_link()
                self.state, self.message = "error", str(e) or type(e).__name__

    def _open_video_link(self, wait):
        """A started VideoLink, or None if the camera didn't let FaceWatch connect within wait seconds."""
        link = camera_link.VideoLink(ctx.mi)
        try:
            if link.start(wait):
                return link
        except OSError as e:
            log.warning("Couldn't open the local port for the video (%s)", e)
        link.stop()
        return None

    def _start_video_link(self):
        """FaceWatch's own link for the video (camera_link.py) if it can be had within a while; otherwise go2rtc's
        own until it can (_retry_video_link)."""
        self.video_link = None
        if not self.cfg["own_camera_link"] or not ctx.motor.available() or port_open(GO2RTC_API):
            return  # (a go2rtc started by hand keeps its own link)
        self.video_link = self._open_video_link(wait=15)
        if self.video_link is not None:
            log.info("Camera video: FaceWatch's own link (no drops)")
        else:
            log.warning("Camera video: the camera didn't let FaceWatch connect, so go2rtc's own link is used for now "
                        "(it drops every ~12 s). FaceWatch keeps trying, and switches when it can.")
            threading.Thread(target=self._retry_video_link, daemon=True).start()

    def _retry_video_link(self):
        """Keeps trying FaceWatch's own link, and switches go2rtc over once it works."""
        while True:
            time.sleep(LINK_RETRY_SECONDS)
            if self.state != "on" or self.go2rtc is None or self.video_link is not None or not self.cfg["own_camera_link"]:
                return
            link = self._open_video_link(wait=20)
            if link is None:
                continue
            with self.lock:
                if self.state != "on" or self.go2rtc is None or self.video_link is not None:
                    link.stop()
                    return
                self._stop_go2rtc()
                self.video_link = link
                try:
                    self._start_go2rtc()
                except RuntimeError as e:
                    log.error("Couldn't start go2rtc again: %s", e)
                    return
                threading.Thread(target=self._keep_go2rtc, args=(self.go2rtc,), daemon=True).start()
            log.info("Camera video: switched to FaceWatch's own link (no drops)")

    def _stop_video_link(self):
        if self.video_link is not None:
            self.video_link.stop()
            self.video_link = None

    def _start_go2rtc(self):
        if port_open(GO2RTC_API):
            return  # already running, e.g. started by hand
        if not GO2RTC_EXE.exists():
            raise RuntimeError("go2rtc.exe is missing from the FaceWatch folder.")
        APP_DATA_DIR.mkdir(exist_ok=True)
        self.go2rtc_log = open(APP_DATA_DIR / "go2rtc.log", "ab")
        env = dict(os.environ)
        # go2rtc plays the alarm through ffmpeg, which winget may have installed after this started.
        if ffmpeg := media.find_ffmpeg():
            env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")
        command = [str(GO2RTC_EXE)]
        if self.video_link is not None:
            # go2rtc.yaml, with the camera's stream read from FaceWatch's link.
            command += ["-config", "go2rtc.yaml", "-config", json.dumps({"streams": {self.stream: self.video_link.source}})]
        self.go2rtc = subprocess.Popen(command, cwd=fw.ROOT, stdout=self.go2rtc_log, stderr=subprocess.STDOUT,
                                       env=env, creationflags=media.NO_WINDOW)
        end_with_facewatch(self.go2rtc)
        deadline = time.time() + 15
        while not port_open(GO2RTC_API):
            if self.go2rtc.poll() is not None:
                raise RuntimeError("go2rtc stopped as soon as it started. See app_data/go2rtc.log.")
            if time.time() > deadline:
                raise RuntimeError("go2rtc didn't start within 15 seconds. See app_data/go2rtc.log.")
            time.sleep(0.25)
        log.info("go2rtc started")

    def _keep_go2rtc(self, process):
        while True:
            time.sleep(5)
            with self.lock:
                if self.go2rtc is not process or self.state != "on":
                    return
                if process.poll() is None:
                    continue
                log.warning("go2rtc stopped by itself - starting it again")
                self._stop_go2rtc()
                try:
                    self._start_go2rtc()
                except RuntimeError as e:
                    log.error("Couldn't start go2rtc again: %s", e)
                    return
                if self.go2rtc is None:
                    return  # another go2rtc took its place
                process = self.go2rtc

    def _stop_go2rtc(self):
        if self.go2rtc is not None:
            self.go2rtc.terminate()
            try:
                self.go2rtc.wait(5)
            except subprocess.TimeoutExpired:
                self.go2rtc.kill()
            self.go2rtc = None
            log.info("go2rtc stopped")
        if self.go2rtc_log is not None:
            self.go2rtc_log.close()
            self.go2rtc_log = None

    def stop(self):
        with self.lock:
            if self.watcher is not None:
                self.watcher.stop()
            if self.clips is not None:
                self.clips.stop()
                self.clips = None
            if self.speaker is not None:
                self.speaker.stop()
                self.speaker = None
            self._stop_go2rtc()
            self._stop_video_link()
            ctx.motor.close()
            self.state, self.message = "off", "Camera is off"

    def status(self):
        """(state, message), also noticing if recognition crashed or the video is still connecting."""
        w = self.watcher
        if self.state == "on" and not (w and w.running):
            return "error", "Face recognition stopped because of an error. See app_data/server.log."
        if self.state == "on" and not w.reader.connected:
            since = w.watchdog.offline_since if w.watchdog else None
            if since:
                return "on", f"No video since {fw.clock(since)}. Check the camera's power and WiFi."
            return "on", "Connecting to the camera…"
        return self.state, self.message

    def reader(self):
        w = self.watcher
        return w.reader if self.state == "on" and w is not None and w.running else None


def face_models():
    try:
        return ctx.camera.models()
    except (Exception, SystemExit) as e:
        log.exception("Could not load the face models")
        raise HTTPException(503, f"Face recognition couldn't start: {e}")


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    """App logins with salted password hashes. Sessions are stored by token hash, never the token itself."""

    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.Lock()
        self.accounts = read_json(folder / "accounts.json", {})
        now = time.time()
        self.sessions = {k: s for k, s in read_json(folder / "sessions.json", {}).items() if s["expires"] > now}
        self.failures = {}

    def _save(self):
        write_json(self.folder / "accounts.json", self.accounts)
        write_json(self.folder / "sessions.json", self.sessions)

    def create(self, username, password):
        with self.lock:
            if username.lower() in (u.lower() for u in self.accounts):
                raise HTTPException(409, "That username is already taken.")
            self.accounts[username] = {"created": datetime.now().isoformat(timespec="seconds")}
            self._set_password(username, password)

    def _set_password(self, username, password):
        salt = secrets.token_bytes(16)
        self.accounts[username].update(salt=salt.hex(), hash=hash_password(password, salt))
        self._save()

    def set_password(self, username, password):
        with self.lock:
            self._set_password(username, password)

    def check(self, username, password):
        account = self.accounts.get(username)
        if account is None:
            hash_password(password, b"0" * 16)  # same delay as a real check, so usernames can't be guessed
            return False
        return hmac.compare_digest(account["hash"], hash_password(password, bytes.fromhex(account["salt"])))

    def delete(self, username):
        with self.lock:
            self.accounts.pop(username, None)
            self.sessions = {k: s for k, s in self.sessions.items() if s["user"] != username}
            self._save()

    def start_session(self, username):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token_key(token)] = {"user": username, "expires": time.time() + SESSION_SECONDS}
            self._save()
        return token

    def end_session(self, token):
        with self.lock:
            if self.sessions.pop(token_key(token), None):
                self._save()

    def user_for(self, token):
        session = self.sessions.get(token_key(token)) if token else None
        if not session or session["expires"] < time.time() or session["user"] not in self.accounts:
            return None
        return session["user"]

    def throttle(self, client):
        now = time.time()
        self.failures[client] = [t for t in self.failures.get(client, []) if now - t < 300]
        if len(self.failures[client]) >= 5:
            raise HTTPException(429, "Too many wrong passwords. Wait 5 minutes and try again.")

    def record_failure(self, client):
        self.failures.setdefault(client, []).append(time.time())


def check_csrf(request):
    # Other websites can't add custom headers to requests, so this blocks cross-site form attacks.
    if request.method not in ("GET", "HEAD") and request.headers.get("X-FaceWatch") != "1":
        raise HTTPException(403, "Request blocked.")


def require_user(request: Request):
    user = ctx.accounts.user_for(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Please log in.")
    check_csrf(request)
    return user


def set_session_cookie(request, response, username):
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, ctx.accounts.start_session(username), max_age=SESSION_SECONDS,
                        httponly=True, samesite="lax", secure=https)


def check_new_login(username, password):
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames need 3-32 letters, numbers, dots, dashes or underscores.")
    check_new_password(password)


def check_new_password(password):
    if len(password) < 8:
        raise HTTPException(400, "Passwords need at least 8 characters.")


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class NameBody(BaseModel):
    name: str


@app.get("/api/session")
def session(request: Request):
    return {"user": ctx.accounts.user_for(request.cookies.get(COOKIE)), "needs_setup": not ctx.accounts.accounts}


@app.post("/api/setup")
def setup(body: Credentials, request: Request, response: Response):
    check_csrf(request)
    if ctx.accounts.accounts:
        raise HTTPException(403, "Setup is already done. Please log in.")
    check_new_login(body.username, body.password)
    ctx.accounts.create(body.username, body.password)
    set_session_cookie(request, response, body.username)
    return {"user": body.username}


@app.post("/api/login")
def login(body: Credentials, request: Request, response: Response):
    check_csrf(request)
    client = request.client.host if request.client else "?"
    ctx.accounts.throttle(client)
    if not ctx.accounts.check(body.username, body.password):
        ctx.accounts.record_failure(client)
        raise HTTPException(401, "Wrong username or password.")
    set_session_cookie(request, response, body.username)
    return {"user": body.username}


@app.post("/api/logout")
def logout(request: Request, response: Response, user=Depends(require_user)):
    ctx.accounts.end_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/accounts")
def list_accounts(user=Depends(require_user)):
    return [{"username": name, "created": a["created"]} for name, a in sorted(ctx.accounts.accounts.items())]


@app.post("/api/accounts")
def add_account(body: Credentials, user=Depends(require_user)):
    check_new_login(body.username, body.password)
    ctx.accounts.create(body.username, body.password)
    return {"username": body.username}


@app.delete("/api/accounts/{username}")
def delete_account(username: str, user=Depends(require_user)):
    if username == user:
        raise HTTPException(400, "You can't delete the login you're using.")
    if username not in ctx.accounts.accounts:
        raise HTTPException(404, "Login not found.")
    ctx.accounts.delete(username)
    return {"ok": True}


@app.post("/api/password")
def change_password(body: PasswordChange, user=Depends(require_user)):
    if not ctx.accounts.check(user, body.current_password):
        raise HTTPException(400, "Your current password is wrong.")
    check_new_password(body.new_password)
    ctx.accounts.set_password(user, body.new_password)
    return {"ok": True}


@app.get("/api/status")
def status(user=Depends(require_user)):
    state, message = ctx.camera.status()
    w = ctx.camera.watcher
    live = state == "on" and w.reader.connected
    return {
        "camera": {"state": state, "message": message},
        "camera_name": ctx.cfg["camera_name"],
        "connected": live,
        "video": "go2rtc" if ctx.camera.stream else "pictures",
        "detector": f"{w.engine.name} on the {'GPU' if w.engine.gpu else 'CPU'}" if w else None,
        "detector_note": w.engine.note if w else None,
        "frame": w.frame_size if live else None,
        "in_view": [{"name": n, "score": round(s, 2), "box": [round(float(v)) for v in face[:4]], "zone": zone_name(z)}
                    for (face, n, s), z in zip(w.results, w.places)] if live else [],
        "unknown_seconds": round(w.unknown_seconds, 1) if live else 0,
        "unknown_alert_after": ctx.cfg["unknown_alert_after_seconds"],
        "hidden": [{"box": [round(float(v)) for v in box], "zone": zone_name(zone)}
                   for box, zone in zip(w.hidden, w.hidden_places)] if live else [],
        "hidden_seconds": round(w.hidden_seconds, 1) if live else 0,
        "hidden_alert_after": ctx.cfg["hidden_alert_after_seconds"],
        "person_detection": bool(w and w.engine.people),
        "alarm": bool(ctx.camera.speaker and ctx.camera.speaker.playing("alarm")),
        "speaker": ctx.cfg["camera_speaker"],
        "turn": bool(ctx.camera.stream) and ctx.cfg["camera_control"] and ctx.motor.available(),
        "outdated": code_changed(),
        "zones": {"state": w.zones.state if live else "off",
                  "lines": [[round(float(v)) for v in line] for line in w.zones.lines]
                  if live and w.zones.lines is not None else None},
        "last_alert": w.last_alert if w else None,
    }


def zone_name(zone):
    return fw.ZONE_NAMES[zone] if zone is not None else None


@app.post("/api/camera/start")
def camera_start(user=Depends(require_user)):
    ctx.camera.start()
    return status(user)


@app.post("/api/camera/stop")
def camera_stop(user=Depends(require_user)):
    ctx.camera.stop()
    return status(user)


class Switch(BaseModel):
    on: bool


@app.get("/api/camera/tracking")
def get_tracking(user=Depends(require_user)):
    """The camera's own motion tracking (it turns to follow movement), read through Xiaomi's cloud."""
    try:
        return {"available": True, "on": ctx.mi.motion_tracking(), "error": None}
    except micloud.MiCloudError as e:
        return {"available": False, "on": None, "error": str(e)}


@app.put("/api/camera/tracking")
def set_tracking(body: Switch, user=Depends(require_user)):
    try:
        on = ctx.mi.set_motion_tracking(body.on)
    except micloud.MiCloudError as e:
        raise HTTPException(502, str(e))
    log.info("Motion tracking turned %s by %s", "on" if on else "off", user)
    return {"available": True, "on": on, "error": None}


def control_or_409():
    if not ctx.cfg["camera_control"]:
        raise HTTPException(409, "Turning the camera is off in Settings → Camera arrows.")


def newest_frame():
    reader = ctx.camera.reader()
    return reader.newest(-1)[1] if reader is not None and reader.connected else None


def save_first_origin():
    """With no origin saved yet, the view when the camera first comes on becomes the origin."""
    for _ in range(120):
        time.sleep(1)
        frame = newest_frame()
        if frame is not None:
            if not ctx.motor.has_origin():
                ctx.motor.set_origin(frame)
                log.info("Saved the camera's current view as its origin")
            return


class Move(BaseModel):
    direction: str


@app.post("/api/camera/move")
def move_camera(body: Move, user=Depends(require_user)):
    """The app sends the direction every 0.4 s while an arrow is held, and "stop" when it's let go."""
    if body.direction == "stop":
        ctx.motor.stop()
        return {"ok": True}
    control_or_409()
    if body.direction not in ptz.DIRECTIONS:
        raise HTTPException(400, "The direction must be left, right, up, down or stop.")
    try:
        ctx.motor.hold(body.direction)
    except (ptz.MotorError, micloud.MiCloudError) as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.post("/api/camera/origin")
def go_to_origin(user=Depends(require_user)):
    control_or_409()
    try:
        return {"message": ctx.motor.go_to_origin(newest_frame)}
    except (ptz.MotorError, micloud.MiCloudError) as e:
        raise HTTPException(502, str(e))


@app.put("/api/camera/origin")
def set_origin(user=Depends(require_user)):
    frame = newest_frame()
    if frame is None:
        raise HTTPException(409, "Turn the camera on first.")
    ctx.motor.set_origin(frame)
    log.info("Camera origin set by %s", user)
    return {"ok": True}


@app.websocket("/api/stream")
async def camera_video(ws: WebSocket):
    """The phone's video (or Talk's setup, with ?talk=1), behind the login. Cross-site pages can't use it: the login
    cookie is SameSite=Lax."""
    stream = ctx.camera.stream
    if not ctx.accounts.user_for(ws.cookies.get(COOKIE)) or stream is None or ctx.camera.state != "on":
        await ws.close(code=4403)
        return
    await ws.accept()
    # With ?talk=1 the phone sends its microphone to the talk stream; otherwise it watches the camera.
    talk = ws.query_params.get("talk") == "1"
    first = None
    if not talk:
        # Watching: from the clip recorder when it can (it starts at the latest keyframe).
        try:
            first = await ws.receive_text()
            codecs = str(json.loads(first).get("value", "")).split(",")
        except (WebSocketDisconnect, RuntimeError, ValueError, AttributeError):
            return
        recorder = ctx.camera.clips
        feed = recorder.watch(asyncio.get_running_loop(), codecs) if recorder else None
        if feed:
            await send_feed(ws, recorder, feed)
            return
    target = f"dst={TALK_STREAM}" if talk else f"src={stream}"
    try:
        async with websockets.connect(f"ws://{GO2RTC_API[0]}:{GO2RTC_API[1]}/api/ws?{target}",
                                      max_size=None) as go2rtc:
            async def to_go2rtc():
                if first:
                    await go2rtc.send(first)
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    await go2rtc.send(message.get("text") or message.get("bytes"))

            async def to_phone():
                async for message in go2rtc:
                    await (ws.send_text(message) if isinstance(message, str) else ws.send_bytes(message))

            tasks = [asyncio.create_task(to_go2rtc()), asyncio.create_task(to_phone())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
            # Either side hanging up is normal (phone locked, app closed, camera turned off).
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, websockets.WebSocketException, WebSocketDisconnect):
        pass
    finally:
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


async def send_feed(ws, recorder, feed):
    """Sends a phone the clip recorder's live feed (see media.ClipRecorder.watch) until either side stops."""
    mime, init, backlog, queue = feed

    async def to_phone():
        await ws.send_text(json.dumps({"type": "mse", "value": mime}))
        await ws.send_bytes(init)
        for fragment in backlog:
            await ws.send_bytes(fragment)
        while (fragment := await queue.get()) is not None:
            await ws.send_bytes(fragment)

    async def from_phone():
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass

    tasks = [asyncio.create_task(to_phone()), asyncio.create_task(from_phone())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        recorder.unwatch(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


def on_alert(alert):
    """Sounds the alarm when someone unknown is inside, and adds a clip to alerts about unknown or hidden people."""
    if alert["warning"] == 2 and ctx.cfg["camera_speaker"] and ctx.cfg["alarm_inside"]:
        threading.Thread(target=alarm_for_alert, daemon=True).start()
    if ctx.camera.clips and ctx.cfg["clip_seconds"] and {"Unknown", "Hidden"} & set(alert["names"]):
        threading.Thread(target=save_clip, args=(ctx.camera.clips, alert), daemon=True).start()


def save_clip(clips, alert):
    """Saves the clip beside the snapshot once its second half has happened, and sends it after the photo."""
    half = ctx.cfg["clip_seconds"] / 2
    start, end = alert["time"] - half, alert["time"] + half
    time.sleep(max(0.0, end - time.time()) + 1)
    path = alert["folder"] / f"{alert['base']}.mp4"
    if not clips.save(path, start, end, media.find_ffmpeg()):
        log.warning("There was no video to save as a clip for the %s alert", alert["base"])
        return
    if alert["sent"]:
        ctx.camera.telegram.send_video(path.read_bytes(), f"🎥 {ctx.cfg['camera_name']} · {fw.clock(alert['time'])}")


def speaker_or_409():
    if not ctx.cfg["camera_speaker"]:
        raise HTTPException(409, "The camera speaker is off in Settings.")
    if ctx.camera.video_link is not None:
        raise HTTPException(409, "Talk and the alarm need go2rtc's own camera link: turn off Settings → Camera → "
                                 "Steady video link first.")
    if ctx.camera.reader() is None or ctx.camera.speaker is None:
        raise HTTPException(409, "Turn the camera on first.")
    return ctx.camera.speaker


def set_volume(percent):
    """Sets the camera's speaker volume (through Xiaomi's cloud, about a second). Sound still plays if it fails."""
    try:
        ctx.mi.set_volume(percent)
    except micloud.MiCloudError as e:
        log.warning("Couldn't set the camera's speaker volume: %s", e)


def sound_alarm():
    """Plays the alarm on the camera's speaker. Returns how long it lasts."""
    speaker = speaker_or_409()
    if not media.find_ffmpeg():
        raise HTTPException(409, "The alarm needs ffmpeg. Install it with: winget install Gyan.FFmpeg.Essentials")
    try:
        if not ALARM_SOUND.exists():
            media.make_alarm(ALARM_SOUND)
        set_volume(ctx.cfg["alarm_volume"])
        seconds = media.wav_seconds(ALARM_SOUND) + 1
        speaker.start("alarm", media.sound_file(ALARM_SOUND), seconds)
    except (OSError, RuntimeError) as e:
        log.error("Couldn't sound the alarm: %s", e)
        raise HTTPException(502, f"Couldn't play the alarm: {e}")
    log.warning("Alarm sounded on the camera")
    return seconds


def alarm_for_alert():
    try:
        sound_alarm()
    except HTTPException as e:
        log.error("No alarm: %s", e.detail)


@app.post("/api/alarm/test")
def test_alarm(user=Depends(require_user)):
    return {"seconds": round(sound_alarm(), 1)}


@app.post("/api/sound/stop")
def stop_sound(user=Depends(require_user)):
    """Silences the camera's speaker, whatever is playing. Always allowed, even with the speaker switched off."""
    if ctx.camera.speaker is not None:
        ctx.camera.speaker.stop()
        log.info("Camera speaker silenced by %s", user)
    return {"ok": True}


class TalkSession(BaseModel):
    talk: int


@app.post("/api/talk/start")
def talk_start(user=Depends(require_user)):
    speaker = speaker_or_409()
    set_volume(ctx.cfg["talk_volume"])
    try:
        number = speaker.start("talk", ctx.camera.stream_url(TALK_STREAM), TALK_CHECK_IN, TALK_LIMIT)
    except RuntimeError as e:
        raise HTTPException(502, f"Couldn't reach the camera's speaker: {e}")
    return {"talk": number}


@app.post("/api/talk/alive")
def talk_alive(body: TalkSession, user=Depends(require_user)):
    """The phone checks in while talking, so Talk ends by itself if the page is closed or loses its connection."""
    speaker = ctx.camera.speaker
    return {"talking": bool(speaker and speaker.extend(body.talk, TALK_CHECK_IN))}


@app.post("/api/talk/stop")
def talk_stop(body: TalkSession, user=Depends(require_user)):
    if ctx.camera.speaker is not None:
        ctx.camera.speaker.stop(body.talk)
    return {"ok": True}


@app.post("/api/test/recognise")
def test_recognise(photo: UploadFile = File(...), user=Depends(require_user)):
    """Recognises the faces in a picture from the user's own phone. Test only: nothing is recorded or sent."""
    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too large (20 MB max).")
    image = fw.decode_image(data)
    if image is None:
        raise HTTPException(415, "Can't read this image. Please use a JPG or PNG photo.")
    image = fw.shrink(image, 1280)
    w = face_models()
    names, features = w.db.matrix()
    results = fw.recognise(image, w.engine, names, features, ctx.cfg)
    return {
        "width": image.shape[1],
        "height": image.shape[0],
        "faces": [{"box": [round(float(v)) for v in face[:4]], "name": name, "score": round(score, 2)}
                  for face, name, score in results],
    }


live_picture = {"key": None, "jpg": None}


@app.get("/api/live.jpg")
def live_snapshot(user=Depends(require_user)):
    """The newest picture, for phones that can't play the video stream."""
    reader = ctx.camera.reader()
    frame_id, frame = reader.newest(-1) if reader is not None else (None, None)
    if frame is None:
        raise HTTPException(503, "No video from the camera yet.")
    key = (id(reader), frame_id)
    if live_picture["key"] != key:
        # Encoded once per camera frame, however many phones are watching.
        _, jpg = cv2.imencode(".jpg", fw.shrink(frame, LIVE_WIDTH), [cv2.IMWRITE_JPEG_QUALITY, 72])
        live_picture.update(key=key, jpg=jpg.tobytes())
    return Response(live_picture["jpg"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def check_person_name(name):
    name = name.strip()
    if not PERSON_RE.match(name) or name.lower() == "unknown":
        raise HTTPException(400, "Names can use English letters, numbers, spaces, dots, dashes and underscores "
                                 "(up to 40), and can't be 'Unknown'.")
    return name


def find_person_dir(name):
    """The person's folder, matched without case like Windows does, or None."""
    fw.KNOWN_FACES_DIR.mkdir(exist_ok=True)
    return next((d for d in fw.KNOWN_FACES_DIR.iterdir() if d.is_dir() and d.name.lower() == name.lower()), None)


def person_dir_or_404(name):
    folder = find_person_dir(check_person_name(name))
    if folder is None:
        raise HTTPException(404, "Person not found.")
    return folder


def list_photos(folder):
    return sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in fw.IMAGE_EXTS)


def file_in(folder, name, pattern=PHOTO_RE):
    if not pattern.match(name):
        raise HTTPException(400, "Bad file name.")
    path = folder / name
    if not path.is_file():
        raise HTTPException(404, "File not found.")
    return path


def add_face_photo(folder, image, strict):
    """Checks the photo has one usable face, then saves it and teaches it to the recogniser right away."""
    w = face_models()
    upright, face, count = fw.find_main_face(w.engine, fw.shrink(image, 1280))
    if face is None:
        raise HTTPException(422, "No face found. Look straight at the camera in good light.")
    if strict and count > 1:
        raise HTTPException(422, "More than one face found. Only the person being added should be in the photo.")
    if min(face[2], face[3]) < (80 if strict else ctx.cfg["min_face_size"]):
        raise HTTPException(422, "The face is too small. Move closer to the camera.")
    feature = w.engine.embed(upright, face)
    names, features = w.db.matrix()
    match, score = fw.identify(feature, names, features, ctx.cfg["match_threshold"])
    warning = None
    if match not in ("Unknown", folder.name):
        warning = f"This face also looks like {match} ({score:.2f}). Make sure it's really {folder.name}."
    path = folder / f"{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
    fw.save_image(path, upright)
    w.db.add(folder.name, path, feature)
    return {"file": path.name, "warning": warning}


@app.get("/api/people")
def list_people(user=Depends(require_user)):
    fw.KNOWN_FACES_DIR.mkdir(exist_ok=True)
    people = []
    for folder in sorted((d for d in fw.KNOWN_FACES_DIR.iterdir() if d.is_dir()), key=lambda d: d.name.lower()):
        photos = list_photos(folder)
        people.append({"name": folder.name, "photo_count": len(photos), "cover": photos[0] if photos else None})
    return people


@app.post("/api/people")
def add_person(body: NameBody, user=Depends(require_user)):
    name = check_person_name(body.name)
    if find_person_dir(name):
        raise HTTPException(409, f"{name} already exists.")
    (fw.KNOWN_FACES_DIR / name).mkdir(parents=True)
    return {"name": name}


@app.get("/api/people/{name}")
def get_person(name: str, user=Depends(require_user)):
    folder = person_dir_or_404(name)
    return {"name": folder.name, "photos": list_photos(folder)}


@app.patch("/api/people/{name}")
def rename_person(name: str, body: NameBody, user=Depends(require_user)):
    folder = person_dir_or_404(name)
    new_name = check_person_name(body.name)
    existing = find_person_dir(new_name)
    if existing and existing != folder:
        raise HTTPException(409, f"{new_name} already exists.")
    if folder.name != new_name:
        folder.rename(fw.KNOWN_FACES_DIR / new_name)
        if ctx.camera.watcher:
            ctx.camera.watcher.db.rename_person(folder.name, new_name)
    return {"name": new_name}


@app.delete("/api/people/{name}")
def delete_person(name: str, user=Depends(require_user)):
    folder = person_dir_or_404(name)
    shutil.rmtree(folder)
    if ctx.camera.watcher:
        ctx.camera.watcher.db.remove_person(folder.name)
    return {"ok": True}


avatar_cache = {}


def face_thumbnail(path, size=160):
    """A square close-up of the face in a photo, for the app's round profile pictures."""
    image = fw.read_image(path)
    if image is None:
        raise HTTPException(404, "Photo not found.")
    image = fw.shrink(image, 1280)
    try:
        upright, face, _ = fw.find_main_face(face_models().engine, image)
    except HTTPException:
        upright, face = None, None
    if face is None:
        upright = image
        h, w = image.shape[:2]
        cx, cy, side = w / 2, h / 2, min(w, h)
    else:
        h, w = upright.shape[:2]
        x, y, fw_, fh = face[:4]
        cx, cy, side = x + fw_ / 2, y + fh / 2, min(max(fw_, fh) * 1.9, w, h)
    x1 = int(min(max(cx - side / 2, 0), w - side))
    y1 = int(min(max(cy - side / 2, 0), h - side))
    crop = upright[y1:y1 + int(side), x1:x1 + int(side)]
    thumb = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


@app.get("/api/people/{name}/avatar")
def person_avatar(name: str, user=Depends(require_user)):
    folder = person_dir_or_404(name)
    photos = list_photos(folder)
    if not photos:
        raise HTTPException(404, "No photos yet.")
    path = folder / photos[0]
    key = (str(path), path.stat().st_mtime)
    if key not in avatar_cache:
        avatar_cache[key] = face_thumbnail(path)
    # The app adds the photo's name to the address, so a changed picture gets a new address.
    return Response(avatar_cache[key], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/people/{name}/photos/{file}")
def get_photo(name: str, file: str, user=Depends(require_user)):
    return FileResponse(file_in(person_dir_or_404(name), file))


@app.post("/api/people/{name}/photos")
def upload_photo(name: str, photo: UploadFile = File(...), user=Depends(require_user)):
    folder = person_dir_or_404(name)
    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too large (20 MB max).")
    image = fw.decode_image(data)
    if image is None:
        raise HTTPException(415, "Can't read this image. Please use a JPG or PNG photo.")
    return add_face_photo(folder, image, strict=True)


@app.delete("/api/people/{name}/photos/{file}")
def delete_photo(name: str, file: str, user=Depends(require_user)):
    path = file_in(person_dir_or_404(name), file)
    path.unlink()
    if ctx.camera.watcher:
        ctx.camera.watcher.db.remove_photo(path)
    return {"ok": True}


def day_dir(date):
    if not DATE_RE.match(date) or not (fw.SNAPSHOTS_DIR / date).is_dir():
        raise HTTPException(404, "Not found.")
    return fw.SNAPSHOTS_DIR / date


@app.get("/api/alerts")
def list_alerts(limit: int = 100, user=Depends(require_user)):
    alerts = []
    if not fw.SNAPSHOTS_DIR.is_dir():
        return alerts
    days = sorted((d for d in fw.SNAPSHOTS_DIR.iterdir() if d.is_dir() and DATE_RE.match(d.name)), reverse=True)
    for day in days:
        for snap, names, warning, faces in day_alerts(day):
            base = snap.stem
            alerts.append({"date": day.name, "file": snap.name, "faces": faces, "names": names,
                           "warning": warning, "time": f"{day.name}T{base[:2]}:{base[2:4]}:{base[4:]}",
                           "clip": f"{base}.mp4" if (day / f"{base}.mp4").exists() else None})
            if len(alerts) >= limit:
                return alerts
    return alerts


def day_alerts(day):
    """One day's alerts, newest first: (snapshot, names, zone warning or None, face pictures)."""
    faces_dir = day / "faces"
    face_files = sorted(f.name for f in faces_dir.glob("*.jpg")) if faces_dir.is_dir() else []
    for snap in sorted((f for f in day.iterdir() if SNAPSHOT_RE.match(f.name)), reverse=True):
        base = snap.stem
        faces = [{"file": f, "name": face_name(f)} for f in face_files if f.startswith(base + "_")]
        # Newer alerts list everything they were about (e.g. a hidden face) next to the snapshot.
        try:
            details = read_json(day / f"{base}.json", {})
        except ValueError:
            details = {}
        names = details.get("names") or list(dict.fromkeys(f["name"] for f in faces))
        yield snap, names, details.get("warning"), faces


thumbnail_cache = {}


@app.get("/api/alerts/{date}/{file}")
def get_alert_file(date: str, file: str, thumb: bool = False, user=Depends(require_user)):
    """An alert's snapshot (or a small copy of it with thumb), or its video clip."""
    if CLIP_RE.match(file):
        return FileResponse(file_in(day_dir(date), file, CLIP_RE), media_type="video/mp4")
    path = file_in(day_dir(date), file, SNAPSHOT_RE)
    if not thumb:
        return FileResponse(path)
    # 2K snapshots are large; the history list only needs small pictures.
    key = (str(path), path.stat().st_mtime)
    if key not in thumbnail_cache:
        if len(thumbnail_cache) > 500:
            thumbnail_cache.clear()
        image = fw.read_image(path)
        if image is None:
            raise HTTPException(404, "File not found.")
        thumbnail_cache[key] = cv2.imencode(".jpg", fw.shrink(image, 320), [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
    return Response(thumbnail_cache[key], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.delete("/api/alerts/{date}/{file}")
def delete_alert(date: str, file: str, user=Depends(require_user)):
    folder = day_dir(date)
    remove_alert(folder, file_in(folder, file, SNAPSHOT_RE))
    return {"ok": True}


def snapshot_days():
    if not fw.SNAPSHOTS_DIR.is_dir():
        return []
    return sorted(d for d in fw.SNAPSHOTS_DIR.iterdir() if d.is_dir() and DATE_RE.match(d.name))


def face_name(file):
    """The name in a face picture's file name: <time>_<index>_<name>.jpg"""
    return Path(file).stem.split("_", 2)[-1]


def remove_alert(folder, snapshot):
    """Deletes a snapshot with its details, clip and face pictures, and the day's folder once it's empty."""
    snapshot.unlink()
    for extra in (".json", ".mp4"):
        snapshot.with_suffix(extra).unlink(missing_ok=True)
    faces_dir = folder / "faces"
    if faces_dir.is_dir():
        for face in faces_dir.glob(snapshot.stem + "_*.jpg"):
            face.unlink()
    tidy(folder)


def tidy(folder):
    for empty in (folder / "faces", folder):
        if empty.is_dir() and not any(empty.iterdir()):
            empty.rmdir()


class AlertRef(BaseModel):
    date: str
    file: str


class DeleteAlerts(BaseModel):
    items: list[AlertRef] = []
    all: bool = False
    unknown_only: bool = False


@app.get("/api/alerts/summary")
def alerts_summary(user=Depends(require_user)):
    alerts = faces = unknown_faces = size = 0
    for day in snapshot_days():
        size += sum(f.stat().st_size for f in day.rglob("*") if f.is_file())
        alerts += sum(1 for f in day.iterdir() if SNAPSHOT_RE.match(f.name))
        for face in (day / "faces").glob("*.jpg"):
            faces += 1
            unknown_faces += face_name(face.name) == "Unknown"
    return {"alerts": alerts, "faces": faces, "unknown_faces": unknown_faces, "bytes": size}


@app.post("/api/alerts/delete")
def delete_alerts(body: DeleteAlerts, user=Depends(require_user)):
    deleted = 0
    if body.all:
        for day in snapshot_days():
            deleted += sum(1 for f in day.iterdir() if SNAPSHOT_RE.match(f.name))
            shutil.rmtree(day)
        thumbnail_cache.clear()
        return {"deleted": deleted}
    for item in body.items:
        try:
            folder = day_dir(item.date)
            snapshot = file_in(folder, item.file, SNAPSHOT_RE)
        except HTTPException:
            continue  # already gone
        remove_alert(folder, snapshot)
        deleted += 1
    return {"deleted": deleted}


@app.post("/api/alerts/faces/delete")
def delete_alert_faces(body: DeleteAlerts, user=Depends(require_user)):
    """Deletes chosen face pictures from Alerts, or all (or all Unknown) ones. Snapshots stay."""
    deleted = 0
    if body.all:
        for day in snapshot_days():
            for face in (day / "faces").glob("*.jpg"):
                if not body.unknown_only or face_name(face.name) == "Unknown":
                    face.unlink()
                    deleted += 1
            tidy(day)
        return {"deleted": deleted}
    for item in body.items:
        try:
            face = file_in(day_dir(item.date) / "faces", item.file)
        except HTTPException:
            continue
        face.unlink()
        tidy(face.parent.parent)
        deleted += 1
    return {"deleted": deleted}


@app.get("/api/alerts/{date}/faces/{file}")
def get_alert_face(date: str, file: str, user=Depends(require_user)):
    return FileResponse(file_in(day_dir(date) / "faces", file))


@app.post("/api/alerts/{date}/faces/{file}/assign")
def assign_alert_face(date: str, file: str, body: NameBody, user=Depends(require_user)):
    return label_face(date, file, body.name)


def label_face(date, file, name):
    """Adds a face the camera saved to a person (made if they don't exist yet), so they're recognised from now on."""
    image = fw.read_image(file_in(day_dir(date) / "faces", file))
    name = check_person_name(name)
    folder = find_person_dir(name)
    created = folder is None
    if created:
        folder = fw.KNOWN_FACES_DIR / name
        folder.mkdir(parents=True)
    try:
        result = add_face_photo(folder, image, strict=False)
    except HTTPException:
        if created:
            folder.rmdir()
        raise
    return {**result, "name": folder.name}


class TelegramBot:
    """The alert buttons ("It's …" / "Ignore") and the bot commands. Only the chat in config.json is answered."""

    COMMANDS = [("photo", "A picture from the camera now"), ("away", "Alerts on: I'm out"),
                ("home", "Pause people alerts: I'm home"), ("status", "The camera and alerts right now"),
                ("summary", "Today so far"), ("help", "What I can do")]

    MAX_PEOPLE = 8
    MAX_PENDING = 200

    def __init__(self, telegram, folder):
        self.telegram = telegram
        self.path = folder / "telegram_buttons.json"
        self.lock = threading.Lock()
        self.pending = read_json(self.path, {})

    def buttons(self, date, file):
        fw.KNOWN_FACES_DIR.mkdir(exist_ok=True)
        people = sorted((d.name for d in fw.KNOWN_FACES_DIR.iterdir() if d.is_dir()), key=str.lower)[:self.MAX_PEOPLE]
        token = secrets.token_urlsafe(6)
        with self.lock:
            self.pending[token] = {"date": date, "file": file, "people": people, "time": time.time()}
            for old in sorted(self.pending, key=lambda t: self.pending[t]["time"])[:-self.MAX_PENDING]:
                del self.pending[old]
            write_json(self.path, self.pending)
        names = [{"text": f"It's {name}", "callback_data": f"{token}:{i}"} for i, name in enumerate(people)]
        rows = [names[j:j + 2] for j in range(0, len(names), 2)]
        return {"inline_keyboard": rows + [[{"text": "Ignore", "callback_data": f"{token}:x"}]]}

    def run(self):
        self.telegram.call("setMyCommands", {"commands": json.dumps(
            [{"command": name, "description": text} for name, text in self.COMMANDS])})
        offset = None
        while True:
            data = {"timeout": 30, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                data["offset"] = offset
            reply = self.telegram.call("getUpdates", data, timeout=45)
            if reply is None:
                time.sleep(30)
                continue
            for update in reply.get("result", []):
                offset = update["update_id"] + 1
                try:
                    if "callback_query" in update:
                        self.handle(update["callback_query"])
                    elif "message" in update:
                        self.command(update["message"])
                except Exception:
                    log.exception("Couldn't handle a message from Telegram")

    def command(self, message):
        chat = str((message.get("chat") or {}).get("id"))
        text = (message.get("text") or "").strip()
        if chat != self.telegram.chat_id or not text.startswith("/"):
            return
        name = text.split()[0][1:].split("@")[0].lower()
        log.info("Telegram command: /%s", name)
        if name == "photo":
            threading.Thread(target=self.photo, args=(chat,), daemon=True).start()
        elif name in ("home", "away"):
            try:
                save_config({"home_mode": name == "home"})
                self.reply(chat, "🏠 Home mode: no people alerts here until you send /away. They're still saved in "
                                 "the app." if name == "home" else "🔔 Away mode: you'll get alerts again.")
            except HTTPException as e:
                self.reply(chat, f"⚠️ {e.detail}")
        elif name == "status":
            self.reply(chat, status_text())
        elif name == "summary":
            self.telegram.call("sendMessage", summary_message(date.today(), chat))
        else:
            self.reply(chat, "\n".join([f"/{command} - {text}" for command, text in self.COMMANDS]))

    def reply(self, chat, text):
        self.telegram.call("sendMessage", {"chat_id": chat, "text": text})

    def photo(self, chat):
        if ctx.camera.state not in ("on", "starting"):
            self.reply(chat, "Turning the camera on…")
            ctx.camera.start()
        deadline = time.time() + 90
        while (frame := newest_frame()) is None and time.time() < deadline and ctx.camera.state != "error":
            time.sleep(1)
        if frame is None:
            self.reply(chat, f"⚠️ Couldn't get a picture: {ctx.camera.message}")
            return
        jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        self.telegram.call("sendPhoto", {"chat_id": chat, "caption": f"📷 {ctx.cfg['camera_name']} · {fw.clock(time.time())}"},
                           {"photo": ("photo.jpg", jpg, "image/jpeg")}, timeout=60)

    def handle(self, query):
        message = query.get("message") or {}
        chat = str((message.get("chat") or {}).get("id"))
        if chat != self.telegram.chat_id:
            self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": "Not allowed."})
            return
        token, _, choice = str(query.get("data", "")).partition(":")
        with self.lock:
            entry = self.pending.pop(token, None)
            write_json(self.path, self.pending)
        if entry is None:
            outcome = "Already done."
        elif choice == "x":
            outcome = "🙈 Ignored"
        else:
            try:
                result = label_face(entry["date"], entry["file"], entry["people"][int(choice)])
                outcome = f"✅ Added to {result['name']}"
                if result["warning"]:
                    outcome += f"\n⚠️ {result['warning']}"
            except (ValueError, IndexError):
                outcome = "⚠️ That button is out of date."
            except HTTPException as e:
                outcome = f"⚠️ Couldn't add this face: {e.detail}"
        log.info("Telegram button: %s", outcome.replace("\n", " "))
        self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": outcome[:200]})
        if entry is not None:
            caption = f"{message.get('caption', '')}\n\n{outcome}"[:1024]
            self.telegram.call("editMessageCaption", {"chat_id": chat, "message_id": message.get("message_id"),
                                                      "caption": caption,
                                                      "reply_markup": json.dumps({"inline_keyboard": []})})


def status_text():
    state, message = ctx.camera.status()
    w = ctx.camera.watcher
    lines = [f"📷 {ctx.cfg['camera_name']}: " + ("on" if state == "on" else message.lower() if state != "off" else "off "
                                                 "(open Live or send /photo to turn it on)"),
             "🏠 Home mode: people alerts are paused (/away to resume)." if ctx.cfg["home_mode"]
             else "🔔 Away mode: alerts are on (/home to pause them)."]
    if w and w.last_alert:
        last = datetime.fromisoformat(w.last_alert["time"])
        lines.append(f"Last alert: {fw.clock(last.timestamp())}, {', '.join(w.last_alert['names'])}")
    return "\n".join(lines)


def summary_message(day, chat):
    """The day's summary as a sendMessage request: counts of what was recorded, and a button to open Alerts."""
    unknown = hidden = 0
    warnings, known = Counter(), Counter()
    folder = fw.SNAPSHOTS_DIR / day.isoformat()
    for _, names, warning, _ in day_alerts(folder) if folder.is_dir() else []:
        if warning:
            warnings[warning] += 1
        elif "Unknown" in names:
            unknown += 1
        hidden += "Hidden" in names
        known.update(n for n in names if n not in ("Unknown", "Hidden"))

    def times(n, what):
        return f"{n} {what}{'' if n == 1 else 's'}"

    lines = [f"📋 {ctx.cfg['camera_name']} · {'today' if day == date.today() else f'{day:%d %b}'} ({day:%a %d %b})"]
    if unknown:
        lines.append(f"⚠️ {times(unknown, 'alert')} about unknown people")
    lines += [f"🚨 {times(n, 'warning')}: unknown person {'inside' if zone == 'Inside' else 'at the entrance'}"
              for zone, n in sorted(warnings.items())]
    if hidden:
        lines.append(f"👤 {times(hidden, 'alert')} about someone hiding their face")
    lines += [f"✅ {name} seen {times(n, 'time')}" for name, n in known.most_common()]
    if len(lines) == 1:
        lines.append("Nobody was recorded. 👍")
    request = {"chat_id": chat, "text": "\n".join(lines)}
    if link := app_link():
        request["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": "Open Alerts", "url": f"{link}/#/alerts"}]]})
    return request


_app_link = []


def app_link():
    """The app's https:// address on Tailscale (as `tailscale serve` gives it), or None."""
    if not _app_link:
        exe = shutil.which("tailscale") or Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        try:
            done = subprocess.run([str(exe), "status", "--json"], capture_output=True, timeout=10,
                                  creationflags=media.NO_WINDOW)
            name = json.loads(done.stdout)["Self"]["DNSName"].rstrip(".")
            _app_link.append(f"https://{name}" if name else None)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
            _app_link.append(None)
    return _app_link[0]


def keep_summarising(telegram):
    """Sends the day's summary once a day at summary_hour, or as soon as FaceWatch is running after that."""
    path = APP_DATA_DIR / "telegram_state.json"
    while True:
        now = datetime.now()
        state = read_json(path, {})
        if summary_due(now, state.get("summary")):
            telegram.queue("sendMessage", summary_message(now.date(), telegram.chat_id))
            write_json(path, {**state, "summary": now.date().isoformat()})
            log.info("Daily summary sent to Telegram")
        time.sleep(60)


def summary_due(now, last_sent):
    """Whether today's summary should go now; last_sent is the date (yyyy-mm-dd) the last one went."""
    return bool(ctx.cfg["daily_summary"] and now.hour >= ctx.cfg["summary_hour"] and last_sent != now.date().isoformat())


def set_awake(on):
    # ES_CONTINUOUS, plus ES_SYSTEM_REQUIRED while on. It lasts until this same thread changes it.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def keep_awake():
    """Asks Windows not to sleep while the camera is on, like a video player does."""
    if os.name != "nt":
        return
    awake = False
    while True:
        on = ctx.camera is not None and ctx.camera.state == "on"
        if on != awake:
            set_awake(on)
            awake = on
            log.info("Keeping the laptop awake while the camera is on" if on else "The laptop may sleep again")
        time.sleep(5)


def drive_camera():
    """Follow faces and the automatic return to the origin (see ptz.Autopilot), a few times a second."""
    pilot = ptz.Autopilot(ctx.motor)
    while True:
        time.sleep(0.3)
        w = ctx.camera.watcher
        if (w is None or not ctx.cfg["camera_control"] or not ctx.camera.stream or ctx.camera.reader() is None
                or not ctx.motor.available()):
            continue
        pilot.motor = ctx.motor
        targets = [(*map(float, face[:4]), name not in ("Unknown", "Unclear")) for face, name, _ in w.results]
        # Someone whose face is hidden: aim at where their head is.
        targets += [(float(x), float(y), float(bw), float(bh) * 0.4, False) for x, y, bw, bh in w.hidden]
        try:
            pilot.tick(time.time(), ctx.cfg, targets, w.results_time, w.frame_size, newest_frame)
        except Exception:
            log.exception("Couldn't turn the camera by itself")
            time.sleep(30)


def clean_old_alerts():
    days = ctx.cfg["keep_alert_days"]
    if not days:
        return 0
    oldest_kept = date.today() - timedelta(days=days - 1)
    removed = 0
    for day in snapshot_days():
        try:
            too_old = date.fromisoformat(day.name) < oldest_kept
        except ValueError:
            continue
        if too_old:
            shutil.rmtree(day)
            removed += 1
    if removed:
        thumbnail_cache.clear()
        log.info("Deleted alerts from %d day(s), keeping the last %d days", removed, days)
    return removed


def keep_cleaning():
    while True:
        try:
            clean_old_alerts()
        except OSError:
            log.exception("Couldn't delete old alerts")
        time.sleep(3600)


@app.get("/api/settings")
def get_settings(user=Depends(require_user)):
    return {key: ctx.cfg[key] for key in SETTINGS}


@app.put("/api/settings")
def put_settings(body: dict, user=Depends(require_user)):
    clean = {}
    for key, value in body.items():
        if key not in SETTINGS:
            raise HTTPException(400, f"Unknown setting: {key}")
        rule, label = SETTINGS[key]
        if rule is bool:
            if not isinstance(value, bool):
                raise HTTPException(400, f"{label} must be on or off.")
        elif rule is str:
            value = str(value).strip()[:40]
            if not value:
                raise HTTPException(400, f"{label} can't be empty.")
        else:
            low, high = rule
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                unit = " seconds" if key.endswith("_seconds") else ""
                raise HTTPException(400, f"{label} must be between {low} and {high}{unit}.")
            value = int(value) if float(value).is_integer() else round(float(value), 3)
        clean[key] = value
    save_config(clean)
    if "keep_alert_days" in clean:
        clean_old_alerts()
    speaker = ctx.camera.speaker
    if clean.get("camera_speaker") is False and speaker:
        speaker.stop()
    if clean.get("camera_control") is False:
        ctx.motor.stop()
    if "own_camera_link" in clean and ctx.camera.state == "on":
        # Switching between links means starting go2rtc again, so the camera restarts.
        threading.Thread(target=lambda: (ctx.camera.stop(), ctx.camera.start()), daemon=True).start()
    # Moving a volume slider while that sound is playing changes it straight away.
    for kind in ("talk", "alarm"):
        if f"{kind}_volume" in clean and speaker and speaker.playing(kind):
            threading.Thread(target=set_volume, args=(clean[f"{kind}_volume"],), daemon=True).start()
    return get_settings(user)


def save_config(changes):
    try:
        saved = json.loads(ctx.config_path.read_text(encoding="utf-8")) if ctx.config_path.exists() else {}
    except json.JSONDecodeError:
        raise HTTPException(500, "config.json has a typo, so settings can't be saved. Fix it on the laptop first.")
    saved.update(changes)
    write_json(ctx.config_path, saved)
    ctx.cfg.update(changes)


class ZoneLines(BaseModel):
    lines: list[list[float]]


@app.get("/api/zones")
def get_zones(user=Depends(require_user)):
    zones = ctx.cfg.get("zones")
    return {"lines": zones["lines"] if zones else None}


@app.put("/api/zones")
def put_zones(body: ZoneLines, user=Depends(require_user)):
    """Saves the two lines (as fractions of the picture) and the picture they were drawn on, used to find them again
    when the camera turns."""
    lines = body.lines
    if len(lines) != 2 or any(len(line) != 4 or not all(0 <= v <= 1 for v in line) for line in lines):
        raise HTTPException(400, "Zones need two lines inside the picture.")
    first, second = (np.float32(line) for line in lines)
    if min(np.hypot(*(line[2:] - line[:2])) for line in (first, second)) < 0.05:
        raise HTTPException(400, "A line is too short. Drag its two dots further apart.")
    if fw.side(first, (second[:2] + second[2:]) / 2) == 0 or fw.side(second, (first[:2] + first[2:]) / 2) == 0:
        raise HTTPException(400, "The two lines are on top of each other. Move them apart.")
    reader = ctx.camera.reader()
    frame = reader.newest(-1)[1] if reader is not None else None
    if frame is None:
        raise HTTPException(409, "Turn the camera on first, so the lines can be saved with its picture.")
    fw.save_image(fw.ZONE_REFERENCE, fw.shrink(frame, 1280))
    save_config({"zones": {"lines": [[round(v, 4) for v in line] for line in lines]}})
    return get_zones(user)


@app.delete("/api/zones")
def delete_zones(user=Depends(require_user)):
    save_config({"zones": None})
    fw.ZONE_REFERENCE.unlink(missing_ok=True)
    return {"lines": None}


class AppFiles(StaticFiles):
    """Makes phones check for a newer version of the app's files every time, so updates show up at once."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", AppFiles(directory=WEB_DIR, html=True), name="web")


def local_addresses():
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos if not info[4][0].startswith("127.")})


def setup_logging():
    APP_DATA_DIR.mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(APP_DATA_DIR / "server.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is None:
        # No console (pythonw.exe from autostart.bat): stray output goes to a file.
        sys.stdout = sys.stderr = open(APP_DATA_DIR / "console.log", "a", buffering=1, encoding="utf-8")
    else:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=handlers)


def main():
    parser = argparse.ArgumentParser(description="FaceWatch: face recognition alerts plus the phone app")
    parser.add_argument("--config", default=str(fw.ROOT / "config.json"), help="path to the config file")
    parser.add_argument("--source", help="override stream_url, e.g. 0 for the laptop webcam")
    parser.add_argument("--port", type=int, default=8000, help="port for the app (default 8000)")
    args = parser.parse_args()

    setup_logging()
    if port_open(("127.0.0.1", args.port)):
        log.info("FaceWatch is already running. Open http://localhost:%d", args.port)
        return
    ctx.config_path = Path(args.config)
    ctx.cfg = fw.load_config(ctx.config_path)
    ctx.accounts = Accounts(APP_DATA_DIR)
    telegram = fw.Telegram(ctx.cfg["telegram_bot_token"], ctx.cfg["telegram_chat_id"])
    if telegram.enabled:
        bot = TelegramBot(telegram, APP_DATA_DIR)
        telegram.label_buttons = bot.buttons
        threading.Thread(target=bot.run, daemon=True).start()
        threading.Thread(target=keep_summarising, args=(telegram,), daemon=True).start()
    for job in (keep_cleaning, keep_awake, drive_camera):
        threading.Thread(target=job, daemon=True).start()
    ctx.camera = Camera(ctx.cfg, fw.resolve_source(ctx.cfg, args.source), telegram)
    if ctx.cfg["camera_autostart"]:
        ctx.camera.start()
    else:
        # Loads the face models (~10 s) now, so opening Live doesn't wait for them.
        threading.Thread(target=ctx.camera.models, daemon=True).start()

    log.info("App ready. The camera turns on when someone opens Live. Open the app at:")
    log.info("  this laptop:            http://localhost:%d", args.port)
    for address in local_addresses():
        where = "Tailscale" if address.startswith("100.") else "phone on the same WiFi"
        log.info("  %-22s  http://%s:%d", where + ":", address, args.port)
    if not ctx.accounts.accounts:
        log.info("Open the app to create the first login.")
    try:
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning", access_log=False)
    finally:
        ctx.camera.stop()


if __name__ == "__main__":
    main()
