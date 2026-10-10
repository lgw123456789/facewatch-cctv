import argparse
import collections
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Must be set before importing cv2. RTSP over TCP avoids corrupted frames on WiFi.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

if os.name == "nt":
    import ctypes

    # Windows Smart App Control blocks some PyTorch files. Without this, each block shows a "Bad Image"
    # pop-up that freezes FaceWatch until someone clicks OK; with it, the file is just skipped.
    SEM_FAILCRITICALERRORS, SEM_NOGPFAULTERRORBOX, SEM_NOOPENFILEERRORBOX = 0x0001, 0x0002, 0x8000
    ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)

import cv2
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
KNOWN_FACES_DIR = ROOT / "known_faces"
SNAPSHOTS_DIR = ROOT / "snapshots"
ZONE_REFERENCE = ROOT / "app_data" / "zone_reference.jpg"
ZONE_NAMES = ("Outside", "Entrance", "Inside")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WINDOW_TITLE = "FaceWatch - press q to quit"

MODEL_ZOO_URL = "https://github.com/opencv/opencv_zoo/raw/main/models"
YOLO_RELEASE_URL = "https://github.com/zjykzj/YOLO11Face/releases/download/v1.0.0"
PERSON_RELEASE_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0"
RECOGNIZER_MODEL = "face_recognition_sface_2021dec.onnx"
RECOGNIZER_URL = f"{MODEL_ZOO_URL}/face_recognition_sface/{RECOGNIZER_MODEL}"
# OpenCV 5 needs the 2026 YuNet model (dynamic input size); OpenCV 4 needs the 2023 one.
YUNET_MODEL = ("face_detection_yunet_2026may.onnx" if int(cv2.__version__.split(".")[0]) >= 5
               else "face_detection_yunet_2023mar.onnx")
YUNET_URL = f"{MODEL_ZOO_URL}/face_detection_yunet/{YUNET_MODEL}"

DEFAULT_CONFIG = {
    "stream_url": "rtsp://127.0.0.1:8554/xiaomi_cam",
    "camera_name": "Home camera",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "device": "cpu",
    "detector": "auto",
    "yolo_model": "yolo11s-pose_widerface.pt",
    "yolo_runtime": "openvino",
    "person_model": "yolo11n.pt",
    "detect_confidence": 0.5,
    "match_threshold": 0.40,
    "unknown_threshold": 0.30,
    "unknown_confirm_frames": 3,
    "clear_face_size": 50,
    "min_face_size": 40,
    "idle_check_seconds": 1.0,
    "detect_width": 1280,
    "process_fps": 10,
    "confirm_frames": 3,
    "cooldown_seconds": 300,
    "camera_autostart": False,
    "notify_known": False,
    "notify_unknown": True,
    "unknown_alert_after_seconds": 10,
    "unknown_grace_seconds": 5,
    "unknown_cooldown_seconds": 60,
    "notify_hidden": True,
    "hidden_alert_after_seconds": 30,
    "hidden_cooldown_seconds": 300,
    "notify_offline": True,
    "offline_alert_after_seconds": 120,
    "zones": None,
    "notify_zones": True,
    "zone_alert_after_seconds": 3,
    "zone_cooldown_seconds": 300,
    "entrance_messages": 3,
    "inside_messages": 5,
    "keep_alert_days": 30,
    "clip_seconds": 10,
    "camera_control": True,
    "own_camera_link": True,
    "follow_faces": False,
    "follow_known": False,
    "origin_return_minutes": 2,
    "home_mode": False,
    "daily_summary": True,
    "summary_hour": 21,
    # Off until go2rtc fixes issue #2175: go2rtc 1.9.14 turns every sound sent to a Xiaomi camera into loud static.
    "camera_speaker": False,
    "alarm_inside": False,
    "alarm_volume": 100,
    "talk_volume": 70,
}

# Someone whose face can't be seen is most likely a household member if one was recognised this recently.
KNOWN_NEARBY_SECONDS = 60

log = logging.getLogger("facewatch")


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if not path.exists():
        log.warning("%s not found - using default settings", path.name)
        return cfg
    try:
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path.name} has a typo on line {e.lineno}: {e.msg}")
    return cfg


def download_model(filename, url):
    path = MODELS_DIR / filename
    if not path.exists():
        MODELS_DIR.mkdir(exist_ok=True)
        log.info("Downloading model %s (first time only)...", filename)
        tmp = path.with_name(filename + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)
        except urllib.error.URLError as e:
            raise SystemExit(f"Could not download {filename} ({e}) - check the name and your internet.")
        if tmp.stat().st_size < 100_000:
            tmp.unlink()
            raise SystemExit(f"Download of {filename} looks broken - check your internet and try again.")
        tmp.replace(path)
    return str(path)


def decode_image(data):
    array = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR) if array.size else None


def read_image(path):
    return decode_image(np.fromfile(str(path), dtype=np.uint8))


def save_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if ok:
        buf.tofile(str(path))


def shrink(image, max_side):
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return image
    return cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def crop_face(image, face, pad=0.6):
    x, y, w, h = face[:4]
    img_h, img_w = image.shape[:2]
    x1, y1 = int(max(0, x - pad * w)), int(max(0, y - pad * h))
    x2, y2 = int(min(img_w, x + w * (1 + pad))), int(min(img_h, y + h * (1 + pad)))
    return image[y1:y2, x1:x2]


def draw(image, results, unknown_seconds=0.0, hidden=(), lines=None):
    thickness = max(2, image.shape[1] // 640)
    font_scale = max(0.6, image.shape[1] / 1600)
    for x1, y1, x2, y2 in np.asarray(lines if lines is not None else (), dtype=int).reshape(-1, 4):
        cv2.line(image, (x1, y1), (x2, y2), (66, 77, 255), thickness)
    for x, y, w, h in np.asarray(hidden, dtype=int).reshape(-1, 4):
        cv2.rectangle(image, (x, y), (x + w, y + h), (59, 169, 242), thickness)
        cv2.putText(image, "Face hidden", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (59, 169, 242),
                    thickness)
    for face, name, score in results:
        x, y, w, h = face[:4].astype(int)
        color = {"Unknown": (0, 0, 255), "Unclear": (160, 160, 160)}.get(name, (0, 200, 0))
        label = "Not clear" if name == "Unclear" else f"{name} {score:.2f}"
        cv2.rectangle(image, (x, y), (x + w, y + h), color, thickness)
        cv2.putText(image, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)
    if unknown_seconds:
        cv2.putText(image, f"Unknown in view: {unknown_seconds:.1f}s", (10, int(40 * font_scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 255), thickness)
    return image


class PresenceTimer:
    """Counts how long someone has been in view. Gaps up to grace_seconds keep the count going."""

    def __init__(self, grace_seconds):
        self.grace = grace_seconds
        self.started = None
        self.last_seen = None

    def update(self, seen, now):
        if seen:
            if self.started is None or now - self.last_seen > self.grace:
                self.started = now
            self.last_seen = now
        elif self.started is not None and now - self.last_seen > self.grace:
            self.started = self.last_seen = None
        return 0.0 if self.started is None else now - self.started


def duration(seconds):
    minutes = round(seconds / 60)
    if seconds < 90:
        return f"{seconds:.0f} s"
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def clock(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%I:%M %p").lstrip("0")


class Watchdog:
    """Tells Telegram when the video stops and comes back, and when the laptop was asleep."""

    def __init__(self, cfg, telegram, now):
        self.cfg, self.telegram = cfg, telegram
        self.quiet_since = self.last_tick = now
        self.offline_since = None

    def tick(self, got_frame, now):
        name = self.cfg["camera_name"]
        # The watch loop runs many times a second, so a long gap means the laptop was asleep.
        if now - self.last_tick > 60:
            self._send(f"⏸️ FaceWatch was paused for {duration(now - self.last_tick)} ({clock(self.last_tick)} to "
                       f"{clock(now)}), probably because the laptop was asleep. Watching {name} again now.")
            self.quiet_since = max(self.quiet_since, now)
        self.last_tick = now
        if got_frame:
            if self.offline_since is not None:
                self._send(f"✅ {name} camera is back online (no video for {duration(now - self.offline_since)}, "
                           f"since {clock(self.offline_since)}).")
                self.offline_since = None
            self.quiet_since = now
        elif self.offline_since is None and now - self.quiet_since >= self.cfg["offline_alert_after_seconds"]:
            self.offline_since = self.quiet_since
            self._send(f"📵 {name} camera is offline: no video for {duration(now - self.quiet_since)}. "
                       "Check its power and WiFi.")

    def _send(self, text):
        log.warning(text)
        if self.cfg["notify_offline"] and self.telegram.enabled:
            self.telegram.send_text(text)


class FaceEngine:
    """Turns faces into fingerprints with SFace. Subclasses' detect() gives a row per face: x, y, w, h, 5 landmarks
    (x, y), confidence."""

    name = ""

    def __init__(self, sface_path, use_gpu=False):
        self.recognizer = cv2.FaceRecognizerSF.create(sface_path, "")
        self.gpu = use_gpu
        self.note = None
        self.people = None  # a PersonDetector, when one can run
        # The models are not thread-safe, and the camera and the app both use them.
        self.lock = threading.RLock()

    def align(self, image, face):
        """The face straightened and cropped to 112x112, the way SFace expects it."""
        with self.lock:
            return self.recognizer.alignCrop(image, face)

    def feature(self, aligned):
        with self.lock:
            feature = self.recognizer.feature(aligned).flatten()
        return feature / np.linalg.norm(feature)

    def embed(self, image, face):
        return self.feature(self.align(image, face))


def is_clear(face, aligned, cfg):
    """Whether a face is big, frontal and sharp enough to call it nobody we know."""
    x, y, w, h = face[:4]
    if min(w, h) < cfg["clear_face_size"] or face[14] < 0.6:
        return False
    left_eye, right_eye, nose = face[4], face[6], face[8]
    to_left, to_right = nose - left_eye, right_eye - nose
    # Seen from the front, the nose sits between the eyes; a turned head pushes it towards one side.
    if to_left <= 0 or to_right <= 0 or not 0.4 <= to_left / to_right <= 2.5:
        return False
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var() >= 30


class FaceTracker:
    """Follows faces between frames: a recognised face keeps its name while it turns away, and a face is Unknown only
    after several clear frames matching nobody."""

    def __init__(self):
        self.tracks = []

    def update(self, results, now, confirm):
        shown, used = [], set()
        for face, name, score in results:
            track = self._match(face, used)
            if track is None:
                track = {"name": None, "unknown": 0, "doubt": 0}
                self.tracks.append(track)
            used.add(id(track))
            track["box"], track["last"] = face[:4].copy(), now
            if name not in ("Unknown", "Unclear"):
                track["name"], track["doubt"] = name, 0
            elif name == "Unknown":
                track["unknown"] += 1
                if track["name"]:
                    # A clear face that matches nobody, again and again: someone else took this spot.
                    track["doubt"] += 1
                    if track["doubt"] >= confirm:
                        track["name"] = None
            if track["name"]:
                shown.append((face, track["name"], score))
            else:
                shown.append((face, "Unknown" if track["unknown"] >= confirm else "Unclear", score))
        self.tracks = [t for t in self.tracks if now - t["last"] < 3.0]
        return shown

    def _match(self, face, used):
        return best_match(self.tracks, face[:4], used, 0.2)


def overlap(a, b):
    """How much two x, y, w, h boxes overlap: 0 (not at all) to 1 (the same box)."""
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy / (a[2] * a[3] + b[2] * b[3] - ix * iy)


def best_match(tracks, box, used, minimum):
    best, best_overlap = None, minimum
    for track in tracks:
        if id(track) not in used and (o := overlap(box, track["box"])) > best_overlap:
            best, best_overlap = track, o
    return best


class PersonTracker:
    """Follows whole people between checks. Ones who moved but never showed a face count as "face hidden" (moving
    keeps posters and coats out)."""

    def __init__(self):
        self.tracks = []

    def update(self, boxes, faces, now, keep_seconds):
        used = set()
        for box in boxes:
            track = best_match(self.tracks, box, used, 0.3)
            if track is None:
                track = {"start": box, "who": None, "moved": False}
                self.tracks.append(track)
            used.add(id(track))
            track["box"], track["last"] = box, now
            x, y, w, h = box
            sx, sy, sw, sh = track["start"]
            if abs(x + w / 2 - sx - sw / 2) + abs(y + h / 2 - sy - sh / 2) > 0.15 * h:
                track["moved"] = True
            for face, name, _ in faces:
                cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
                if name != "Unclear" and x <= cx <= x + w and y <= cy <= y + h:
                    track["who"] = name
        self.tracks = [t for t in self.tracks if now - t["last"] <= keep_seconds]
        return [t["box"] for t in self.tracks if id(t) in used and t["who"] is None and t["moved"]]


def side(line, point):
    """Positive on one side of the (endless) line through x1, y1, x2, y2, negative on the other."""
    x1, y1, x2, y2 = line
    return (x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1)


def standing_point(face, bodies):
    """Where someone stands: the bottom middle of the body box around their face, else the face itself."""
    cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
    for x, y, w, h in bodies:
        if x <= cx <= x + w and y <= cy <= y + h:
            return x + w / 2, y + h
    return cx, cy


class ViewMatcher:
    """Finds how the picture moved since a saved one, the way panorama photos are stitched (used for the zones and
    for turning the camera back to its origin)."""

    WIDTH = 640

    def __init__(self):
        self.orb = cv2.ORB_create(2000)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.clahe = cv2.createCLAHE(2.0, (8, 8))

    def features(self, image):
        h, w = image.shape[:2]
        small = cv2.resize(image, (self.WIDTH, round(h * self.WIDTH / w)), interpolation=cv2.INTER_AREA)
        gray = self.clahe.apply(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        mask = np.full(gray.shape, 255, np.uint8)
        # The camera's clock in the top-left corner stays put when the camera turns, so it mustn't be matched.
        mask[:gray.shape[0] // 12, :gray.shape[1] // 3] = 0
        keypoints, descriptors = self.orb.detectAndCompute(gray, mask)
        return keypoints, descriptors, (gray.shape[1], gray.shape[0])

    def match(self, reference, frame):
        """The homography from the reference (from features()) to this frame, or None if they can't be matched
        reliably. Both are in WIDTH-wide pixels."""
        ref_points, ref_descriptors, (w, h) = reference
        points, descriptors, _ = self.features(frame)
        if ref_descriptors is None or descriptors is None or len(points) < 30:
            return None
        pairs = self.matcher.knnMatch(ref_descriptors, descriptors, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 25:
            return None
        src = np.float32([ref_points[m.queryIdx].pt for m in good])
        dst = np.float32([points[m.trainIdx].pt for m in good])
        homography, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if homography is None or inliers.sum() < 20 or inliers.sum() < 0.3 * len(good):
            return None
        # A wide-angle lens stretches the edges a lot when it turns, so only the middle of the picture is checked:
        # it must keep a sensible size and shape, or the match is wrong (or the turn too big to trust).
        middle = np.float32([[w / 4, h / 4], [w * 3 / 4, h / 4], [w * 3 / 4, h * 3 / 4], [w / 4, h * 3 / 4]])
        moved = cv2.perspectiveTransform(middle.reshape(-1, 1, 2), homography).reshape(-1, 2)
        if not 0.33 < cv2.contourArea(moved) / (w * h / 4) < 3 or not cv2.isContourConvex(moved):
            return None
        # Treat tiny differences as no movement, so the lines don't jitter.
        return np.eye(3) if np.abs(moved - middle).max() < 2 else homography

    def offset(self, reference, frame):
        """Where the middle of the reference picture is now, as (x, y) from the middle of this frame in WIDTH-wide
        pixels, or None if the pictures can't be matched."""
        homography = self.match(reference, frame)
        if homography is None:
            return None
        w, h = reference[2]
        x, y = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), homography)[0, 0]
        fh, fw = frame.shape[:2]
        return float(x - self.WIDTH / 2), float(y - fh * self.WIDTH / fw / 2)


class Zones:
    """Outside, Entrance and Inside, split by the two lines drawn in the app. When the camera turns, the picture is
    matched to the one saved with the lines; if that fails for a while, zones pause."""

    CHECK_SECONDS = 3
    GIVE_UP_SECONDS = 15

    def __init__(self, cfg):
        self.cfg = cfg
        self.view = ViewMatcher()
        self.loaded, self.reference = None, None
        self.lines, self.state = None, "off"
        self.last_try = self.last_ok = 0.0

    def update(self, frame, now):
        setting = self.cfg.get("zones")
        if not setting or not ZONE_REFERENCE.exists():
            self.lines, self.state, self.loaded = None, "off", None
            return
        key = (json.dumps(setting), ZONE_REFERENCE.stat().st_mtime)
        if key != self.loaded:
            image = read_image(ZONE_REFERENCE)
            if image is None:
                self.lines, self.state = None, "off"
                return
            self.reference, self.loaded = self.view.features(image), key
            self.last_try, self.last_ok = 0.0, now
        if now - self.last_try < self.CHECK_SECONDS:
            return
        self.last_try = now
        homography = self.view.match(self.reference, frame)
        if homography is not None:
            ref_w, ref_h = self.reference[2]
            points = np.float32(setting["lines"]).reshape(-1, 1, 2) * np.float32([ref_w, ref_h])
            scale = frame.shape[1] / ViewMatcher.WIDTH
            self.lines = cv2.perspectiveTransform(points, homography).reshape(2, 4) * scale
            self.state, self.last_ok = "on", now
        elif now - self.last_ok > self.GIVE_UP_SECONDS:
            self.lines, self.state = None, "lost"

    def zone_of(self, point):
        """0 (Outside), 1 (Entrance) or 2 (Inside), or None while the zones are off or paused."""
        if self.lines is None:
            return None
        first, second = self.lines
        # Outside is the side of the first line away from the second; Inside, the side of the second away from the first.
        if side(first, point) * side(first, (second[:2] + second[2:]) / 2) < 0:
            return 0
        if side(second, point) * side(second, (first[:2] + first[2:]) / 2) < 0:
            return 2
        return 1


class YuNetEngine(FaceEngine):
    """OpenCV's built-in face detector, for when PyTorch can't run."""

    name = "YuNet"

    def __init__(self, yunet_path, sface_path):
        super().__init__(sface_path)
        self.detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 320), 0.8, 0.3, 5000)

    def detect(self, image, imgsz=640):
        small = shrink(image, imgsz)
        scale = small.shape[1] / image.shape[1]
        with self.lock:
            self.detector.setInputSize((small.shape[1], small.shape[0]))
            _, faces = self.detector.detect(small)
        if faces is None:
            return np.empty((0, 15), dtype=np.float32)
        faces[:, :14] /= scale
        return faces


class YoloEngine(FaceEngine):
    name = "YOLO"

    def __init__(self, detector, sface_path, confidence, device="cpu"):
        super().__init__(sface_path, use_gpu=device == 0)
        self.detector = detector
        self.confidence = confidence
        self.device = device
        if device == "intel:cpu":
            self.name = "YOLO (OpenVINO)"

    def detect(self, image, imgsz=640):
        with self.lock:
            result = self.detector.predict(image, imgsz=imgsz, conf=self.confidence, device=self.device,
                                           verbose=False)[0]
        if result.keypoints is None or len(result.boxes) == 0:
            return np.empty((0, 15), dtype=np.float32)
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        points = result.keypoints.xy.cpu().numpy()
        if result.keypoints.conf is not None:
            # How sure YOLO is about the eyes, nose and mouth; low for heads that are turned away.
            scores = np.minimum(scores, result.keypoints.conf.cpu().numpy().mean(axis=1))
        faces = []
        for (x1, y1, x2, y2), score, pts in zip(boxes, scores, points):
            # Hidden landmarks come back as (0, 0); such faces can't be aligned for recognition.
            if not pts.all():
                continue
            # SFace's alignment template expects the image-left eye and mouth corner first.
            if pts[0, 0] > pts[1, 0]:
                pts[[0, 1]] = pts[[1, 0]]
            if pts[3, 0] > pts[4, 0]:
                pts[[3, 4]] = pts[[4, 3]]
            faces.append([x1, y1, x2 - x1, y2 - y1, *pts.ravel(), score])
        return np.array(faces, dtype=np.float32).reshape(-1, 15)


class PersonDetector:
    def __init__(self, model, device):
        self.model, self.device = model, device

    def detect(self, image):
        """One x, y, w, h box per person."""
        result = self.model.predict(image, imgsz=640, conf=0.5, classes=[0], device=self.device, verbose=False)[0]
        boxes = result.boxes.xyxy.cpu().numpy()
        boxes[:, 2:] -= boxes[:, :2]
        return boxes


def openvino_copy(YOLO, pt_path, task, imgsz):
    """An 8-bit OpenVINO copy of the model (about 1.7x faster on Intel CPUs), made once and calibrated on the
    snapshots and known faces."""
    folder = pt_path.with_name(f"{pt_path.stem}_int8_openvino_model")
    if folder.exists():
        return folder
    photos = [p for p in [*SNAPSHOTS_DIR.glob("*/*.jpg"), *KNOWN_FACES_DIR.glob("*/*")] if p.suffix.lower() in IMAGE_EXTS]
    if not photos:
        raise RuntimeError("it needs a few photos to tune itself, so add someone first")
    log.info("Making the faster OpenVINO version of %s (first time only, about a minute)...", pt_path.name)
    logging.getLogger("nncf").setLevel(logging.WARNING)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for i, photo in enumerate(photos[-300:]):
            image = read_image(photo)
            if image is not None:
                save_image(tmp / "images" / f"{i}.jpg", shrink(image, imgsz))
        landmarks = "kpt_shape: [5, 3]\n" if task == "pose" else ""
        (tmp / "data.yaml").write_text(f"path: {tmp.as_posix()}\ntrain: images\nval: images\n{landmarks}"
                                       "names:\n  0: object\n", encoding="utf-8")
        YOLO(str(pt_path), task=task).export(format="openvino", int8=True, dynamic=True, imgsz=imgsz,
                                             data=str(tmp / "data.yaml"), fraction=1.0, verbose=False)
    return folder


def load_yolo(YOLO, pt_path, task, cfg, imgsz):
    """(model, device): the OpenVINO version when it works, otherwise the original PyTorch one."""
    if str(cfg["yolo_runtime"]).lower() == "openvino":
        try:
            model = YOLO(str(openvino_copy(YOLO, Path(pt_path), task, imgsz)), task=task)
            model.predict(np.zeros((64, 64, 3), np.uint8), imgsz=64, device="intel:cpu", verbose=False)
            return model, "intel:cpu"
        except Exception as e:
            log.warning("OpenVINO isn't available for %s (%s) - using PyTorch", Path(pt_path).name, e)
    return YOLO(str(pt_path), task=task), "cpu"


def create_yolo_engine(cfg, sface_path):
    if "pose" not in cfg["yolo_model"]:
        raise SystemExit("yolo_model must be a '-pose' model: face recognition needs its face landmarks.")
    yolo_path = download_model(cfg["yolo_model"], f"{YOLO_RELEASE_URL}/{cfg['yolo_model']}")
    wants_gpu = str(cfg["device"]).lower() == "gpu"
    if not wants_gpu:
        # Hides the GPU from PyTorch, so nothing can use it or warn about its driver.
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        os.environ["PYTORCH_NVML_BASED_CUDA_CHECK"] = "1"
    # Stops Ultralytics from going online by itself (installing packages, update checks, usage statistics).
    os.environ.setdefault("YOLO_OFFLINE", "1")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    # PyTorch's helper threads otherwise keep spinning for a moment after every check, which made FaceWatch use
    # ~4 CPU cores while watching an empty room. Letting them sleep cut that to half a core at the same speed.
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    os.environ.setdefault("KMP_BLOCKTIME", "0")
    # Imported here rather than at the top, so the app's server starts instantly and still runs if this fails.
    try:
        import torch
        from ultralytics import YOLO
    except ImportError as e:
        raise RuntimeError("PyTorch or Ultralytics isn't installed.") from e
    except OSError as e:
        if getattr(e, "winerror", None) == 4551:
            raise RuntimeError("Windows Smart App Control blocks PyTorch, which YOLO needs.") from e
        raise RuntimeError(f"PyTorch couldn't load ({e}).") from e
    # Ultralytics limits OpenCV to one thread when imported, which makes SFace about 6x slower.
    cv2.setNumThreads(max(1, (os.cpu_count() or 2) // 2))
    use_gpu = wants_gpu and torch.cuda.is_available()
    if wants_gpu and not use_gpu:
        log.warning("device is set to \"gpu\" but no usable NVIDIA GPU was found - using the CPU")
    if use_gpu:
        engine = YoloEngine(YOLO(yolo_path, task="pose"), sface_path, cfg["detect_confidence"], 0)
        log.info("Face detection: YOLO on the GPU (%s)", torch.cuda.get_device_name(0))
    else:
        model, device = load_yolo(YOLO, yolo_path, "pose", cfg, 1280)
        engine = YoloEngine(model, sface_path, cfg["detect_confidence"], device)
        log.info("Face detection: %s on the CPU", engine.name)
    try:
        person_path = download_model(cfg["person_model"], f"{PERSON_RELEASE_URL}/{cfg['person_model']}")
        engine.people = PersonDetector(*load_yolo(YOLO, person_path, "detect", cfg, 640))
    except (Exception, SystemExit) as e:
        log.warning("Person detection is off (%s), so there are no alerts for hidden faces", e)
    return engine


def create_engine(cfg):
    """YOLO when it can run; with "detector": "auto", OpenCV's YuNet when it can't (e.g. PyTorch is blocked)."""
    choice = str(cfg["detector"]).lower()
    if choice not in ("auto", "yolo", "yunet"):
        raise SystemExit('"detector" in config.json must be "auto", "yolo" or "yunet".')
    sface_path = download_model(RECOGNIZER_MODEL, RECOGNIZER_URL)
    note = None
    if choice != "yunet":
        try:
            return create_yolo_engine(cfg, sface_path)
        except RuntimeError as e:
            if choice == "yolo":
                raise
            note = f"YOLO isn't available: {e} Using OpenCV's YuNet face detector instead."
            log.warning(note)
    engine = YuNetEngine(download_model(YUNET_MODEL, YUNET_URL), sface_path)
    engine.note = note
    log.info("Face detection: YuNet on the CPU")
    return engine


def find_main_face(engine, image):
    """Biggest face in a photo. Tries smaller sizes (YuNet misses faces over ~300 px) and sideways rotations."""
    for rotation in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        rotated = image if rotation is None else cv2.rotate(image, rotation)
        for max_side in (1280, 640, 320):
            candidate = shrink(rotated, max_side)
            faces = engine.detect(candidate, max_side)
            if len(faces):
                return candidate, max(faces, key=lambda f: f[2] * f[3]), len(faces)
    return None, None, 0


class FaceDatabase:
    """One face fingerprint per photo in known_faces/<name>/. Can be changed while the camera is running."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = []
        self._names, self._features = [], np.empty((0, 128), dtype=np.float32)

    def load(self, engine):
        KNOWN_FACES_DIR.mkdir(exist_ok=True)
        entries = []
        for person_dir in sorted(p for p in KNOWN_FACES_DIR.iterdir() if p.is_dir()):
            loaded = 0
            for photo in sorted(person_dir.iterdir()):
                if photo.suffix.lower() not in IMAGE_EXTS:
                    continue
                image = read_image(photo)
                if image is None:
                    log.warning("  could not read %s - skipped", photo.relative_to(ROOT))
                    continue
                image, face, face_count = find_main_face(engine, shrink(image, 1280))
                if face is None:
                    log.warning("  no face found in %s - skipped", photo.relative_to(ROOT))
                    continue
                if face_count > 1:
                    log.warning("  %s has %d faces - using the biggest one", photo.relative_to(ROOT), face_count)
                entries.append((person_dir.name, photo, engine.embed(image, face)))
                loaded += 1
            log.info("Loaded %d photo(s) of %s", loaded, person_dir.name)
        if not entries:
            log.warning("No known faces yet - everyone will show as 'Unknown'. Add photos to known_faces/<name>/")
        with self.lock:
            self.entries = entries
            self._rebuild()

    def _rebuild(self):
        self._names = [person for person, _, _ in self.entries]
        self._features = np.array([f for _, _, f in self.entries], dtype=np.float32).reshape(-1, 128)

    def matrix(self):
        """(names, features) with one row per photo, for identify()."""
        with self.lock:
            return self._names, self._features

    def add(self, person, photo, feature):
        with self.lock:
            self.entries.append((person, photo, feature))
            self._rebuild()

    def remove_photo(self, photo):
        with self.lock:
            self.entries = [e for e in self.entries if e[1] != photo]
            self._rebuild()

    def remove_person(self, person):
        with self.lock:
            self.entries = [e for e in self.entries if e[0] != person]
            self._rebuild()

    def rename_person(self, old, new):
        with self.lock:
            self.entries = [(new, KNOWN_FACES_DIR / new / photo.name, f) if person == old else (person, photo, f)
                            for person, photo, f in self.entries]
            self._rebuild()


def identify(feature, known_names, known_features, threshold):
    if not known_names:
        return "Unknown", 0.0
    similarities = known_features @ feature
    best = int(np.argmax(similarities))
    score = float(similarities[best])
    return (known_names[best] if score >= threshold else "Unknown"), score


def recognise(frame, engine, known_names, known_features, cfg):
    """One (face, name, score) per face. name is a known person, "Unknown" when the face is clear and
    matches nobody, or "Unclear" when the face can't be judged (turned away, too small, blurred, or a near miss)."""
    # Never enlarge small video for detection: it costs time and adds no detail. YOLO needs multiples of 32.
    imgsz = min(cfg["detect_width"], -(-frame.shape[1] // 32) * 32)
    results = []
    for face in engine.detect(frame, imgsz):
        if min(face[2], face[3]) < cfg["min_face_size"]:
            continue
        aligned = engine.align(frame, face)
        name, score = identify(engine.feature(aligned), known_names, known_features, cfg["match_threshold"])
        if name == "Unknown" and (score >= cfg["unknown_threshold"] or not is_clear(face, aligned, cfg)):
            name = "Unclear"
        results.append((face, name, score))
    return results


def open_capture(source):
    """The video, decoded with one thread when it's streamed: FFmpeg's default spreads decoding over every core, which
    holds back a frame per core (0.5-0.9 s behind on a 16-thread laptop; one thread keeps up at 2K and 20 fps)."""
    threads = getattr(cv2, "CAP_PROP_N_THREADS", None)
    if isinstance(source, str) and threads is not None:
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [threads, 1])
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(source)


class StreamReader:
    """Keeps only the newest frame so slow processing never falls behind the live stream."""

    def __init__(self, source):
        self.source = source
        self.frame = None
        self.frame_id = 0
        self.connected = False
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.running:
            log.info("Connecting to the camera stream...")
            cap = open_capture(self.source)
            if not cap.isOpened():
                log.warning("Could not open the stream - is go2rtc running? Retrying in 5 s")
                time.sleep(5)
                continue
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    log.warning("Stream lost - reconnecting")
                    break
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
                if not self.connected:
                    self.connected = True
                    log.info("Connected")
            self.connected = False
            cap.release()
            time.sleep(2)

    def newest(self, seen_id):
        """Returns (id, frame) of the newest frame, or (seen_id, None) if nothing newer has arrived."""
        with self.lock:
            if self.frame_id == seen_id:
                return seen_id, None
            return self.frame_id, self.frame

    def stop(self):
        self.running = False


class Telegram:
    """Sends through a Telegram bot. Messages wait in an outbox and are retried while Telegram can't be reached (up
    to KEEP_HOURS)."""

    RETRY_SECONDS = 30
    KEEP_HOURS = 6
    LATE_SECONDS = 60
    MAX_WAITING = 100

    def __init__(self, token, chat_id):
        self.token = str(token).strip()
        self.chat_id = str(chat_id).strip()
        self.enabled = bool(self.token and self.chat_id) and "PASTE" not in self.token + self.chat_id
        # Set by the app: (date, face file) -> "who is this?" buttons for an unknown face, or None.
        self.label_buttons = None
        self.lock = threading.Lock()
        self.outbox = collections.deque()  # (method, data, files, timeout, time queued, still worth sending late)
        self.sending = False
        self.retry = threading.Event()
        self.down_since = None

    def call(self, method, data, files=None, timeout=30):
        """The Bot API's reply (a dict), or None if it failed."""
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}",
                              data=data, files=files, timeout=timeout)
        except requests.RequestException as e:
            with self.lock:
                if self.down_since is None:
                    self.down_since = time.time()
                    # The exception text contains the URL, which contains the bot token, so don't log it.
                    log.error("Could not reach Telegram (%s) - check the internet connection. Alerts wait and are "
                              "sent once it's back.", type(e).__name__)
            return None
        with self.lock:
            if self.down_since is not None:
                log.info("Telegram can be reached again (it couldn't for %s)", duration(time.time() - self.down_since))
                self.down_since = None
                self.retry.set()
        if not r.ok:
            log.error("Telegram error %s: %s", r.status_code, r.text[:300])
            return None
        return r.json()

    def queue(self, method, data, files=None, timeout=60, late_ok=True):
        """Sends it through the outbox. late_ok=False drops it if it couldn't go out within LATE_SECONDS."""
        with self.lock:
            self.outbox.append((method, data, files, timeout, time.time(), late_ok))
            while len(self.outbox) > self.MAX_WAITING:
                self.outbox.popleft()
            start, self.sending = not self.sending, True
        if start:
            threading.Thread(target=self._send_outbox, daemon=True).start()

    def _send_outbox(self):
        while True:
            with self.lock:
                if not self.outbox:
                    self.sending = False
                    return
                item = self.outbox[0]
            method, data, files, timeout, queued, late_ok = item
            late = time.time() - queued
            if late < self.KEEP_HOURS * 3600 and (late_ok or late < self.LATE_SECONDS):
                if late >= self.LATE_SECONDS:
                    key = "text" if "text" in data else "caption"
                    data = {**data, key: f"⏱️ Sent late: Telegram couldn't be reached at the time.\n{data.get(key, '')}"}
                if self.call(method, data, files, timeout) is None and self.down_since is not None:
                    self.retry.wait(self.RETRY_SECONDS)
                    self.retry.clear()
                    continue
            with self.lock:
                if self.outbox and self.outbox[0] is item:
                    self.outbox.popleft()

    def send_text(self, text, late_ok=True):
        self.queue("sendMessage", {"chat_id": self.chat_id, "text": text}, late_ok=late_ok)

    def send_video(self, data, caption):
        self.queue("sendVideo", {"chat_id": self.chat_id, "caption": caption, "supports_streaming": "true"},
                   {"video": ("clip.mp4", data, "video/mp4")}, timeout=120)

    def send_photo(self, image, caption, buttons=None, repeat=None, times=1):
        """Sends the photo, then repeats the text so the phone keeps buzzing for a warning."""
        _, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        data = {"chat_id": self.chat_id, "caption": caption}
        if buttons:
            data["reply_markup"] = json.dumps(buttons)
        self.queue("sendPhoto", data, {"photo": ("snapshot.jpg", jpg.tobytes(), "image/jpeg")})

        def remind():
            for i in range(2, times + 1):
                time.sleep(4)
                self.send_text(f"{repeat} ({i}/{times})", late_ok=False)

        if times > 1:
            threading.Thread(target=remind, daemon=True).start()


WARNINGS = {1: "🚨 WARNING: unknown person at the entrance (past the first line)",
            2: "🚨 WARNING: unknown person INSIDE (past the second line)"}


def send_alert(frame, results, names, cfg, telegram, unknown_seconds, hidden=(), hidden_seconds=0.0,
               warning=None, places=(), hidden_places=(), zone_lines=None):
    """Saves the event for the app's Alerts, and sends it to Telegram if the notify_ settings say so. warning is 1 or
    2 past a zone line; places and hidden_places are each person's zone."""
    stamp = datetime.now()
    known = [n for n in names if n not in ("Unknown", "Hidden")]
    text = [WARNINGS[warning]] if warning else []
    if known:
        text.append("✅ " + ", ".join(known))
    if "Unknown" in names and not warning:
        outside = any(n == "Unknown" and zone == 0 for (_, n, _), zone in zip(results, places))
        text.append(f"⚠️ Unknown person{' outside' if outside else ''} (in view for {unknown_seconds:.0f} s)")
    if "Hidden" in names:
        where = {0: " outside", 1: " at the entrance", 2: " inside"}.get(next(iter(hidden_places), None), "")
        text.append(f"👤 Someone{where} has been in view for {hidden_seconds:.0f} s, but their face couldn't be seen")
    text.append(f"📷 {cfg['camera_name']} · {stamp:%d %b %Y, %I:%M:%S %p}")
    # Home mode (/home in Telegram) keeps people alerts out of Telegram; they're still saved for the app.
    send = telegram.enabled and not cfg["home_mode"] and (
        (bool(known) and cfg["notify_known"]) or ("Unknown" in names and not warning and cfg["notify_unknown"])
        or (bool(warning) and cfg["notify_zones"]) or ("Hidden" in names and cfg["notify_hidden"]))
    log.info("%s: %s%s", "ALERT" if send else "Recorded (no Telegram)", ", ".join(names),
             f" ({ZONE_NAMES[warning]})" if warning else "")

    snapshot = draw(frame.copy(), results, unknown_seconds if "Unknown" in names and not warning else 0.0,
                    hidden if "Hidden" in names else (), zone_lines)
    folder = SNAPSHOTS_DIR / f"{stamp:%Y-%m-%d}"
    base = f"{stamp:%H%M%S}"
    save_image(folder / f"{base}.jpg", snapshot)
    for i, (face, name, _) in enumerate(results):
        if name != "Unclear":
            save_image(folder / "faces" / f"{base}_{i}_{name}.jpg", crop_face(frame, face))
    in_view = [name for _, name, _ in results if name != "Unclear"]
    details = {"names": list(dict.fromkeys(in_view + names))}
    if warning:
        details["warning"] = ZONE_NAMES[warning]
    (folder / f"{base}.json").write_text(json.dumps(details), encoding="utf-8")

    if send:
        times = (cfg["inside_messages"] if warning == 2 else cfg["entrance_messages"]) if warning else 1
        repeat = f"{WARNINGS[warning]} · {cfg['camera_name']} {stamp:%I:%M:%S %p}" if warning else None
        unknown = [(face[2] * face[3], i) for i, (face, name, _) in enumerate(results) if name == "Unknown"]
        # "Who is this?" buttons for the biggest unknown face.
        buttons = (telegram.label_buttons(folder.name, f"{base}_{max(unknown)[1]}_Unknown.jpg")
                   if unknown and telegram.label_buttons else None)
        telegram.send_photo(snapshot, "\n".join(text), buttons, repeat, times)
    return {"folder": folder, "base": base, "sent": send}


class FaceWatch:
    def __init__(self, cfg, telegram):
        self.cfg = cfg
        self.telegram = telegram
        self.engine = create_engine(cfg)
        self.db = FaceDatabase()
        self.db.load(self.engine)
        if not telegram.enabled:
            log.warning("Telegram is not set up in config.json - alerts will only be shown here")
        self.results, self.places = [], []
        self.results_time = 0.0
        self.frame_size = None
        self.unknown_seconds = 0.0
        self.hidden, self.hidden_places, self.hidden_seconds = [], [], 0.0
        self.last_alert = None
        self.checks = 0
        self.reader = None
        self.watchdog = None
        self.zones = Zones(cfg)
        # Set by the app: called with each alert's details, to add a video clip or sound the alarm.
        self.on_alert = None
        self._stop = None

    @property
    def running(self):
        return self._stop is not None and not self._stop.is_set()

    def start(self, source):
        self.stop()
        self._stop = threading.Event()
        self.reader = StreamReader(source)
        self.watchdog = Watchdog(self.cfg, self.telegram, time.time())
        threading.Thread(target=self._watch, args=(self.reader, self.watchdog, self._stop), daemon=True).start()
        log.info("Watching '%s'", self.cfg["camera_name"])

    def stop(self):
        if self._stop is not None:
            self._stop.set()
            self.reader.stop()
            log.info("Camera stopped")
        self.results, self.places, self.unknown_seconds = [], [], 0.0
        self.hidden, self.hidden_places, self.hidden_seconds = [], [], 0.0

    def _watch(self, reader, watchdog, stop):
        cfg = self.cfg
        streak, last_alert, last_id = {}, {}, 0
        unknown_timer = PresenceTimer(cfg["unknown_grace_seconds"])
        hidden_timer = PresenceTimer(cfg["unknown_grace_seconds"])
        zone_timers = {1: PresenceTimer(cfg["unknown_grace_seconds"]), 2: PresenceTimer(cfg["unknown_grace_seconds"])}
        timers = [unknown_timer, hidden_timer, *zone_timers.values()]
        tracker, people, zones = FaceTracker(), PersonTracker(), self.zones
        last_check, checked_look, last_known = 0.0, None, 0.0
        try:
            while not stop.is_set():
                started = time.time()
                last_id, frame = reader.newest(last_id)
                watchdog.tick(frame is not None, started)
                if frame is None:
                    time.sleep(0.01)
                    continue

                # Finding faces is the expensive part. While the picture hasn't changed since the last check and
                # nobody is in view, check only every idle_check_seconds instead of on every frame.
                look = cv2.cvtColor(cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                moved = checked_look is None or np.abs(look.astype(np.int16) - checked_look).mean() > 2
                if not moved and not tracker.tracks and started - last_check < cfg["idle_check_seconds"]:
                    self.unknown_seconds, self.hidden_seconds, *_ = [t.update(False, started) for t in timers]
                    time.sleep(0.1)
                    continue
                last_check, checked_look = started, look.astype(np.int16)
                self.checks += 1

                known_names, known_features = self.db.matrix()
                now = time.time()
                found = recognise(frame, self.engine, known_names, known_features, cfg)
                results = tracker.update(found, now, cfg["unknown_confirm_frames"])
                seen = {name for _, name, _ in results} - {"Unclear"}
                if seen - {"Unknown"}:
                    last_known = now
                streak = {name: streak.get(name, 0) + 1 for name in seen}
                zones.update(frame, now)
                bodies = (self.engine.people.detect(frame) if self.engine.people is not None
                          else np.empty((0, 4), np.float32))
                hidden = people.update(bodies, results, now, cfg["unknown_grace_seconds"])
                places = [zones.zone_of(standing_point(face, bodies)) for face, _, _ in results]
                hidden_places = [zones.zone_of((x + w / 2, y + h)) for x, y, w, h in hidden]
                unknown_zones = {zone for (_, name, _), zone in zip(results, places) if name == "Unknown"}
                for timer in timers:
                    timer.grace = cfg["unknown_grace_seconds"]
                # Unknown people past a zone line get a zone warning instead of the normal Unknown alert.
                unknown_seconds = unknown_timer.update(bool(unknown_zones & {None, 0}), now)
                zone_seconds = {zone: timer.update(zone in unknown_zones, now) for zone, timer in zone_timers.items()}
                hidden_seconds = hidden_timer.update(bool(hidden), now)
                self.results, self.places, self.unknown_seconds = results, places, unknown_seconds
                self.hidden, self.hidden_places, self.hidden_seconds = hidden, hidden_places, hidden_seconds
                self.frame_size = (frame.shape[1], frame.shape[0])
                self.results_time = now

                due = []
                for name in seen:
                    if name == "Unknown":
                        ready = unknown_seconds >= cfg["unknown_alert_after_seconds"]
                        cooldown = cfg["unknown_cooldown_seconds"]
                    else:
                        ready = streak[name] >= cfg["confirm_frames"]
                        cooldown = cfg["cooldown_seconds"]
                    if ready and now - last_alert.get(name, 0) >= cooldown:
                        due.append(name)
                        last_alert[name] = now
                if (hidden_seconds >= cfg["hidden_alert_after_seconds"] and now - last_known >= KNOWN_NEARBY_SECONDS
                        and now - last_alert.get("Hidden", 0) >= cfg["hidden_cooldown_seconds"]):
                    due.append("Hidden")
                    last_alert["Hidden"] = now
                # Inside (2) wins over the entrance (1); each zone warns once per zone_cooldown_seconds.
                warning = next((zone for zone in (2, 1) if zone_seconds[zone] >= cfg["zone_alert_after_seconds"]
                                and now - last_alert.get(f"zone {zone}", 0) >= cfg["zone_cooldown_seconds"]), None)
                if warning:
                    last_alert[f"zone {warning}"] = now
                    due = ["Unknown", *(name for name in due if name != "Unknown")]
                if due:
                    alert = send_alert(frame, results, due, cfg, self.telegram, unknown_seconds, hidden,
                                       hidden_seconds, warning, places, hidden_places, zones.lines)
                    self.last_alert = {"time": datetime.now().isoformat(timespec="seconds"), "names": due,
                                       "warning": ZONE_NAMES[warning] if warning else None}
                    if self.on_alert:
                        self.on_alert({**alert, "time": now, "names": due, "warning": warning})

                time.sleep(max(0.0, 1.0 / cfg["process_fps"] - (time.time() - started)))
        except Exception:
            log.exception("Face processing stopped because of an error")
            stop.set()


def resolve_source(cfg, override=None):
    source = override if override is not None else cfg["stream_url"]
    if str(source).isdigit():
        # Faces are close and large on a webcam, so a smaller detection size is enough and much faster.
        cfg["detect_width"] = min(cfg["detect_width"], 640)
        return int(source)
    return source


def run(cfg, source, show, telegram):
    watcher = FaceWatch(cfg, telegram)
    watcher.start(source)
    log.info("Press Ctrl+C to stop.")
    last_id, window_open = 0, False
    try:
        while watcher.running:
            if not show:
                time.sleep(0.5)
                continue
            last_id, frame = watcher.reader.newest(last_id)
            if frame is not None:
                preview = draw(frame.copy(), watcher.results, watcher.unknown_seconds, watcher.hidden,
                               watcher.zones.lines)
                cv2.imshow(WINDOW_TITLE, shrink(preview, 1280))
                window_open = True
            if not window_open:
                time.sleep(0.01)
            elif cv2.waitKey(1 if frame is not None else 5) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        cv2.destroyAllWindows()
        log.info("Stopped")


def main():
    parser = argparse.ArgumentParser(description="Face recognition alerts for a CCTV stream")
    parser.add_argument("--config", default=str(ROOT / "config.json"), help="path to the config file")
    parser.add_argument("--source", help="override stream_url, e.g. 0 for the laptop webcam")
    parser.add_argument("--show", action="store_true", help="show a live preview with names and scores")
    parser.add_argument("--test-alert", action="store_true", help="send a test Telegram message and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(Path(args.config))
    telegram = Telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"])

    if args.test_alert:
        if not telegram.enabled:
            raise SystemExit("Fill in telegram_bot_token and telegram_chat_id in config.json first.")
        if telegram.call("sendMessage", {"chat_id": telegram.chat_id,
                                         "text": f"FaceWatch test from '{cfg['camera_name']}' - notifications work!"}):
            print("Sent - check Telegram on your phone.")
        return

    run(cfg, resolve_source(cfg, args.source), args.show, telegram)


if __name__ == "__main__":
    main()
