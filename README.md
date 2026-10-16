# FaceWatch

Face recognition alerts for a Xiaomi home camera, running on a Windows laptop.

FaceWatch reads the camera's video, recognises the people added to it, and sends a Telegram message with a snapshot
and a short clip when an unknown person shows up. A phone app (a web app that can be added to the home screen) covers
live view, turning the camera, adding people and browsing past alerts.

```
Xiaomi camera ──Wi-Fi──▶ go2rtc ──RTSP──▶ server.py ──▶ Telegram alerts
                      (on the laptop)        │
                                             └──▶ FaceWatch app (phone, tablet or computer)
```

All processing happens on the laptop. Face photos, snapshots and logins stay there. Only the alerts leave the
machine, and those go to the Telegram chat set in `config.json`.

## Features

- Telegram photo and video clip when an unknown person stays in view for a few seconds
- Alert for someone who stays in view without ever showing a face (mask, cap, back turned)
- Gate and door lines; an unknown person past either line triggers louder, repeated warnings
- Camera offline alerts: video stopped, video back, and laptop woke from sleep
- Live view in the app, about 0.2 s behind real time, with name boxes over the video
- Camera control with an on-screen arrow pad, keyboard arrows, full screen and a saved Origin (home) position
- Follow faces: the camera turns towards unknown people on its own, then goes back to the origin
- People can be added from the app with new photos, gallery photos, or faces the camera already saved
- "It's Ali" / "Ignore" buttons under each unknown-person alert in Telegram
- Telegram commands: `/photo`, `/home`, `/away`, `/status`, `/summary`
- Daily summary on Telegram every evening
- Household logins for the app, with hashed passwords
- Remote access through Tailscale, with nothing opened to the internet
- Runs on the CPU; an NVIDIA GPU is optional

## Requirements

- Windows 10 or 11 laptop or PC that stays on, on the same Wi-Fi as the camera
- Python 3.12 (3.10 or newer should work)
- A Xiaomi camera supported by go2rtc. The list is in
  [go2rtc issue #1982](https://github.com/AlexxIT/go2rtc/issues/1982). FaceWatch was built and tested with the
  Xiaomi Smart Camera C301 (`mxiang.camera.c301`).
- A Mi Home account with the camera added to it
- Telegram on a phone
- About 3 GB of free disk space (PyTorch and OpenVINO are big)

Any camera with an RTSP link also works for recognition and alerts (see [Other cameras](#other-cameras)). Turning the
camera and the steady video link are Xiaomi only.

## Setup

### 1. Download FaceWatch and install the libraries

In **Command Prompt**:

```bat
git clone https://github.com/lgw123456789/facewatch-cctv.git
cd facewatch-cctv
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Without Git: **Code → Download ZIP** on GitHub, unzip it, and `cd` into that folder in place of the first two lines.

The install takes a few minutes. In any new terminal, run `.venv\Scripts\activate` inside the folder before any
`python` command. `No module named 'cv2'` means the virtual environment isn't active.

### 2. Add known people

One folder per person inside `known_faces/`, with 3 to 10 photos of that person's face:

```
known_faces/
  Ali/    front.jpg  side.jpg  glasses.jpg
  Mei/    1.jpg  2.jpg  3.jpg
```

- The folder name is the name used in alerts.
- Clear photos from slightly different angles work best (with and without glasses, if worn).
- Each photo should show only that person, or that person as the biggest face.

This step is optional. People can also be added from the app later.

### 3. Test with the laptop's webcam

```bat
python facewatch.py --source 0 --show
```

The first run downloads the models (about 65 MB) into `models/` and builds faster OpenVINO copies, which takes
about a minute, once. A window opens: known faces get a green box with a name and score, unknown faces a red box.
Press `q` to close it.

### 4. Create a Telegram bot

1. In Telegram, open **@BotFather**, send `/newbot` and follow the steps. BotFather replies with a token like
   `123456789:AAH...`.
2. Create the settings file from the example:

   ```bat
   copy config.example.json config.json
   ```

3. Paste the token into `config.json` as `telegram_bot_token`.
4. Open the new bot in Telegram and send it any message.
5. Run the script below and copy the number it prints into `config.json` as `telegram_chat_id`:

   ```bat
   python get_chat_id.py
   ```

6. Send a test alert. A message should arrive in the chat:

   ```bat
   python facewatch.py --test-alert
   ```

The bot token gives full control of the bot, so keep `config.json` private.

### 5. Connect the camera with go2rtc

[go2rtc](https://github.com/AlexxIT/go2rtc) pulls the video from the Xiaomi camera.

1. Download `go2rtc_win64.zip` (v1.9.14 or newer) from the
   [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and put `go2rtc.exe` in the FaceWatch folder.
2. Create its settings file from the example:

   ```bat
   copy go2rtc.example.yaml go2rtc.yaml
   ```

3. Double-click `go2rtc.exe`. If Windows SmartScreen shows a warning, choose **More info → Run anyway**. If the
   firewall asks, allow **Private networks**.
4. Open <http://localhost:1984>, go to **Add → Xiaomi** and log in with the Mi Home account, using the same region as
   the Mi Home app.
5. Copy the camera's `xiaomi://...` link into `go2rtc.yaml` in place of `PASTE_FROM_WEBUI`. Add `&subtype=3` to the
   end for full quality.
6. Restart go2rtc, then click **stream** next to `xiaomi_cam` on its page. Playing video means the connection works.
7. Close go2rtc. From here on FaceWatch starts it automatically.

After the login, `go2rtc.yaml` holds a token for the Mi account, so don't share it. `.gitignore` already keeps it,
`config.json`, the face photos, snapshots and app data out of Git.

### 6. Start FaceWatch

Double-click **`start.bat`** (or run `python server.py`).

The server starts straight away. The camera stays off until someone opens **Live** in the app, or until
**Settings → Camera → Turn on when FaceWatch starts** is switched on. Once on, the camera stays on (and alerts keep
working) until someone taps **Turn off** on the Live page.

1. On the laptop, open <http://localhost:8000> and create the first login. More household logins can be added under
   **Settings → Logins**.
2. On a phone on the same Wi-Fi, open the address the server prints (like `http://192.168.1.10:8000`).

If the firewall asks about Python, allow **Private networks**.

Run only one of `server.py` and `facewatch.py` at a time, otherwise every alert is sent twice. `server.py` does
everything `facewatch.py` does, plus the app.

### 7. Remote access (Tailscale)

[Tailscale](https://tailscale.com) creates a private network between the laptop and the phones. Only devices signed in
to that network can reach the app, and no ports are opened on the router.

1. Install Tailscale on the laptop and on each phone, and sign in to the same network (family members can be invited
   from the Tailscale admin console).
2. In the [DNS settings](https://login.tailscale.com/admin/dns), turn on **MagicDNS** and **HTTPS Certificates**.
3. On the laptop, run this once (the setting survives restarts):

   ```bat
   tailscale serve --bg 8000
   ```

4. `tailscale serve status` shows the app's address, like `https://home-laptop.tail1234.ts.net`. Open it on the phones.

Prefer the `https://` address where possible. Browsers only allow the in-app camera, the microphone and "install app"
on `https://` addresses.

**Adding to the home screen:** on iPhone, open the address in Safari → Share → **Add to Home Screen**. On Android,
open it in Chrome → ⋮ → **Install app**.

### 8. Optional: start with Windows and stay awake

- **`autostart.bat`** makes FaceWatch start silently (no window) at every Windows login. `autostart.bat off` undoes
  it. With no window, the log goes to `app_data/server.log`.
- While the camera is on, FaceWatch asks Windows not to sleep, the same way video players do. Closing the lid still
  puts the laptop to sleep. To keep watching with the lid closed, set the lid-close action to **Do nothing** in
  Windows power options.

## Using the app

| Tab | What it does |
|---|---|
| **Live** | Turns the camera on and shows the video with name boxes, who is in view and the countdown before an alert. Has the arrow pad, full screen, **Origin**, **Test** and **Turn off**. Turning off also stops the alerts. |
| **People** | Everyone FaceWatch knows. Add a person, take photos in the app (front or back camera) or pick from the gallery, rename, delete, or remove a bad photo. Each photo is checked for a clear face first. Changes apply at once. |
| **Test recognition** | Point the phone's camera at someone and see FaceWatch's guess. Nothing is recorded or sent. |
| **Alerts** | History by day with snapshots and clips. **Faces** shows every face the camera saved; tap one to add it to a person. Several can be selected and deleted at once. |
| **Settings** | Camera options, which Telegram messages to send, timers, match strictness, alert retention, zones, logins and password. Changes save immediately. |

The biggest accuracy gain comes from adding a few faces from **Alerts → Faces** to the right people. Camera pictures
are taken from above, through a wide lens, and in black and white at night, so the faces look quite different from phone
photos.

### Turning the camera

The see-through arrow pad in the bottom-left of the video turns the camera: tap for one step, hold to keep turning,
release to stop. Keyboard arrows also work on a computer.

- **Full screen** (bottom-right button) fills the screen with the video and keeps only the arrows on top. On iPhone the
  video fills the page instead. Esc or the same button exits.
- **Origin** sends the camera back to its home position. It reverses the counted steps, then matches the picture
  against the one saved for the origin, so it still works after the camera was moved in Mi Home.
- **Set this view as the origin** makes the current view the new home position. The first time the camera comes on,
  that view becomes the origin automatically.
- **Settings → Camera → Back to origin after** returns the camera automatically some time after the arrows were last
  used (2 minutes by default, 0 disables it).
- **Settings → Camera → Follow faces** turns the camera towards unknown people (or towards everyone, with the option to
  also follow known people) and back to the origin 10 seconds after the person leaves. It stays within 12 steps
  sideways and 5 up or down of the origin, and pauses for 20 seconds after anyone uses the arrows. It replaces the
  camera's own motion tracking, so turning one on turns the other off.
- **Settings → Camera arrows** hides the arrows and Origin completely, for setups where nobody should turn the camera.

The laptop has to be on the same network as the camera. The phone can be anywhere.

### Zones

In **Settings → Zones → Zone lines**, drag two lines onto the floor in the picture: line 1 at the gate and line 2 at
the front door, then **Save**. A person's position decides the zone:

| An unknown person... | Result |
|---|---|
| Outside (before line 1) | The normal unknown-person alert. |
| At the entrance (past line 1) | A warning, sent 3 times a few seconds apart so the phone keeps buzzing. |
| Inside (past line 2) | A warning, sent 5 times. |

Known people never trigger zone warnings. When the camera turns, FaceWatch matches the new picture against the one
saved with the lines and shifts the lines to fit (this works for turns up to about 30°). If the match fails, zones
pause until the camera is back, and the normal unknown-person alert keeps working.

## Telegram

Alerts arrive as a photo labelled with the person's name or "Unknown", followed by a short video clip. Unknown-person
alerts come with a button for each known person (**It's Ali**, **It's Mei**, ...) plus **Ignore**. Tapping a name adds
that face to the person, so the next sighting is recognised.

Commands (also listed in Telegram's **/** menu):

| Command | What it does |
|---|---|
| `/photo` | A picture from the camera right now (turns the camera on if needed). |
| `/home` | Home mode: people alerts stop going to Telegram. The app still saves every alert. |
| `/away` | Alerts back on. |
| `/status` | Camera on or off, the current mode and the last alert. |
| `/summary` | Today's summary so far. |
| `/help` | The list of commands. |

The bot only answers messages from the chat set in `config.json`.

The **daily summary** arrives at 9 pm (adjustable under **Settings → Telegram messages**) with the day's alerts and
who was seen. If the internet or Telegram is down, alerts queue on the laptop and go out once the connection is back,
marked "Sent late" (for up to 6 hours).

## Alarm, Talk and clips

**Clips:** alerts about unknown or hidden people include a video clip, half from before the alert and half after
(10 s by default, 0 disables clips). Clips are cut from the camera's own video, so the CPU cost is close to zero.

**Alarm and Talk** use the camera's speaker. The alarm plays a siren and a spoken warning when an unknown person gets
past line 2. Talk sends voice through the camera from the Live page.

> Both are **off by default**. go2rtc 1.9.14 has a bug that turns any sound sent to a Xiaomi camera into loud static
> ([#2175](https://github.com/AlexxIT/go2rtc/issues/2175), fix in
> [#2406](https://github.com/AlexxIT/go2rtc/pull/2406)). Once a go2rtc release includes the fix, replace `go2rtc.exe`
> and turn on **Settings → Camera speaker → Talk and Alarm**. Talk and Alarm also need **Steady video link** off,
> because both go through go2rtc's own connection.

Both need ffmpeg:

```bat
winget install --id Gyan.FFmpeg.Essentials -e
```

Ways to silence the speaker at any time: **Stop the Alarm** on Live, the **Talk and Alarm** switch, **Turn off**, or
closing FaceWatch. Talk also ends automatically a few seconds after the phone's page closes, and after 5 minutes at
most.

## Steady video link

go2rtc's own connection to Xiaomi cameras drops about every 12 seconds
([go2rtc #2057](https://github.com/AlexxIT/go2rtc/issues/2057)), leaving a second of no video and a few seconds of
broken frames each time. To avoid that, FaceWatch connects to the camera directly with the Mi login go2rtc saved
(Xiaomi's MISS protocol over CS2, the same one go2rtc and Mi Home use) and hands the video to go2rtc on a local port.
go2rtc then serves the app, the clips and face recognition from that feed as usual. The camera arrows share the same
connection, so a tap turns the camera immediately.

On by default. **Settings → Camera → Steady video link** switches back to go2rtc's own connection. If FaceWatch
can't connect when the camera turns on, it falls back to go2rtc's connection and keeps retrying in the background.

## Running without the app

`facewatch.py` runs recognition and alerts on its own, without the app:

| Command | What it does |
|---|---|
| `python facewatch.py` | Watch the camera in the background. |
| `python facewatch.py --show` | Same, with a preview window showing names and scores. |
| `python facewatch.py --source 0` | Use the laptop's webcam instead of the camera. |
| `python facewatch.py --test-alert` | Send a test Telegram message and exit. |
| `python facewatch.py --config other.json` | Use a different settings file. |

`server.py` accepts `--port` (default 8000), `--source` and `--config`.

## Settings (config.json)

Most of these can be changed in the app. Anything missing from `config.json` falls back to the default.

| Setting | Default | What it does |
|---|---|---|
| `stream_url` | `rtsp://127.0.0.1:8554/xiaomi_cam` | Where the video comes from. |
| `camera_name` | Home camera | Used in alerts. |
| `telegram_bot_token` / `telegram_chat_id` | | From step 4. |
| `camera_autostart` | false | Turn the camera on when FaceWatch starts. |
| `match_threshold` | 0.40 | How similar a face must be to count as someone. Family shown as Unknown → lower it (0.36). Strangers getting a name → raise it (0.45). `--show` displays the scores. |
| `unknown_threshold` | 0.30 | A face only counts as Unknown below this score. In between it's "Not clear" and never alerts. |
| `min_face_size` | 40 | Faces smaller than this (pixels) are ignored. |
| `clear_face_size` | 50 | Smaller, turned or blurred faces are "Not clear" rather than Unknown. |
| `unknown_confirm_frames` | 3 | Checks a face must be clearly unknown before it counts as Unknown. |
| `confirm_frames` | 3 | Frames in a row a person must be seen before an alert. |
| `unknown_alert_after_seconds` | 10 | How long an unknown person must be in view before the alert. |
| `unknown_grace_seconds` | 5 | Gaps shorter than this (someone turning away) don't reset that timer. |
| `unknown_cooldown_seconds` | 60 | Minimum time between alerts about the same unknown person. |
| `cooldown_seconds` | 300 | Minimum time between records of the same known person. |
| `notify_unknown` / `notify_known` | true / false | Which people alerts go to Telegram. Everything is saved in the app either way. |
| `notify_hidden` | true | Alert when someone stays in view without showing a face. |
| `hidden_alert_after_seconds` | 30 | How long before that alert. Skipped if someone known was recognised in the last minute. |
| `hidden_cooldown_seconds` | 300 | Minimum time between face-hidden alerts. |
| `notify_offline` | true | Message when the video stops, comes back, or the laptop was asleep. |
| `offline_alert_after_seconds` | 120 | How long the video must be gone first. |
| `notify_zones` | true | Send zone warnings. |
| `zone_alert_after_seconds` | 3 | How long someone must be past a line before the warning. |
| `entrance_messages` / `inside_messages` | 3 / 5 | How many times each warning is sent. |
| `zone_cooldown_seconds` | 300 | Each zone warns at most this often. |
| `zones` | none | The two lines, set from the app. |
| `keep_alert_days` | 30 | Alerts older than this are deleted. 0 keeps everything. |
| `clip_seconds` | 10 | Length of alert clips. 0 turns clips off. |
| `camera_control` | true | Show the arrows and Origin. |
| `own_camera_link` | true | Steady video link (Xiaomi only). |
| `follow_faces` / `follow_known` | false / false | Turn towards unknown people (and known people). |
| `origin_return_minutes` | 2 | Return to the origin this long after the arrows were used. 0 = never. |
| `home_mode` | false | Keep people alerts out of Telegram. |
| `daily_summary` / `summary_hour` | true / 21 | The evening summary and its hour (0–23). |
| `camera_speaker` | false | Allow Talk and the alarm (read the section above before turning it on). |
| `alarm_inside` | false | Play the alarm when an unknown person gets past line 2. |
| `alarm_volume` / `talk_volume` | 100 / 70 | Speaker volume (0–100). |
| `process_fps` | 10 | Most frames per second checked for faces. Lower it if the CPU is busy. |
| `idle_check_seconds` | 1.0 | How often to check when nothing moves and nobody is in view. |
| `detect_width` | 1280 | Size the face detector works at (a multiple of 32). 960 is lighter, but misses far-away faces. |
| `detect_confidence` | 0.5 | How sure the detector must be that something is a face. |
| `detector` | auto | `auto` uses YOLO, or OpenCV's YuNet if PyTorch can't run. `yolo` or `yunet` forces one. |
| `yolo_model` | yolo11s-pose_widerface.pt | The face model. `yolo11n-pose_widerface.pt` is about 3× lighter but less accurate. |
| `yolo_runtime` | openvino | `openvino` is about 1.7× faster on Intel CPUs. `pytorch` uses the original models. |
| `person_model` | yolo11n.pt | Finds whole people, for face-hidden alerts. |
| `device` | cpu | `gpu` uses an NVIDIA GPU if PyTorch can (see below). |

### Using an NVIDIA GPU

Install the CUDA build of PyTorch inside the virtual environment, then set `"device": "gpu"`:

```bat
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
python -c "import torch; print(torch.cuda.is_available())"
```

The last line should print `True`. On startup FaceWatch logs `Face detection is running on the GPU`.

### Other cameras

Any camera with an RTSP stream works for recognition, alerts, clips and the app. Put its `rtsp://...` link in
`stream_url` (or add it as a stream in `go2rtc.yaml`). The arrows, Follow faces, the steady video link and the camera
settings are Xiaomi only, and the motion-tracking and speaker-volume settings are only mapped for the C301 in
`micloud.py`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` or `py` is not recognised | Reinstall Python with **Add to PATH** ticked, then open a new terminal. |
| `No module named 'cv2'` | Run `.venv\Scripts\activate` first. |
| "Could not open the stream" | Check that video plays on go2rtc's page (<http://localhost:1984>) and the stream is called `xiaomi_cam`. |
| Live shows an error | The message says what failed. See `app_data/go2rtc.log` for go2rtc problems and `app_data/server.log` for the rest. |
| Video breaks up | Change `subtype=3` to `subtype=hd` in `go2rtc.yaml` and restart FaceWatch. |
| Alerts are slow or the CPU is busy | Lower `process_fps` or `detect_width`. |
| Family shows as Unknown | Add camera faces from **Alerts → Faces**, or lower `match_threshold` a little. |
| "No face found in known_faces/..." | That photo is too small, blurry or turned. Use a clearer one. |
| Telegram "chat not found" | Wrong `telegram_chat_id`. Message the bot and run `get_chat_id.py` again. |
| "Could not reach Telegram" in the log | Telegram is unreachable right now. Alerts are kept and sent late. |
| The arrows say the camera didn't answer | The laptop must be on the camera's network, and the camera online in Mi Home. |
| The arrows say the camera didn't accept the login | Try again in a minute. If it keeps happening, log in to Xiaomi again on go2rtc's page. |
| Origin says the picture couldn't be matched | It's very dark, or the view changed a lot. Point the camera and tap **Set this view as the origin**. |
| `cs2: pop buffer is full` in `go2rtc.log` | go2rtc is using its own connection. Turn on **Steady video link**; if it's already on, `server.log` shows why the link couldn't connect. |
| Live says "FaceWatch was updated" | The code changed while the old version was running. Close FaceWatch and run `start.bat` again. |
| The phone can't open the app | On Wi-Fi: check the address and that the firewall allows Python on private networks. Away from home: switch Tailscale on. |
| go2rtc's page doesn't open on the phone | Intended. go2rtc has no password, so it only listens on the laptop. |
| `DLL load failed ... Application Control policy has blocked this file` | Windows Smart App Control blocked a library. If it's PyTorch, FaceWatch switches to YuNet automatically (less accurate on far or turned faces). For other libraries, install FaceWatch in a fresh `.venv` of its own. |
| The camera plays loud static | The go2rtc bug described in [Alarm, Talk and clips](#alarm-talk-and-clips). Turn **Talk and Alarm** off. |

## Project layout

```
start.bat              start FaceWatch
autostart.bat          silent start at Windows login (autostart.bat off to undo)
server.py              the app's server, the camera and alerts; starts go2rtc itself
facewatch.py           face detection, recognition, tracking, zones and Telegram; also runs on its own
camera_link.py         the steady video link, handed to go2rtc on a local port
ptz.py                 the Xiaomi camera connection and turning the camera (arrows, Origin, Follow faces)
media.py               alert clips, the Live feed, and the alarm and Talk through go2rtc
micloud.py             camera settings and keys through Xiaomi's cloud, using go2rtc's saved login
get_chat_id.py         prints the Telegram chat ID
web/                   the app (plain HTML, CSS and JavaScript, no build step)
config.example.json    copy to config.json
go2rtc.example.yaml    copy to go2rtc.yaml
```

Created on the first run (and kept out of Git): `known_faces/`, `snapshots/`, `models/`, `app_data/`.

## How it works

- **Detection:** YOLO11 face model (with face landmarks) running on OpenVINO, or OpenCV's YuNet as a fallback. A
  second YOLO11 model finds whole people for the face-hidden alerts.
- **Recognition:** OpenCV's SFace turns each aligned face into a 128-number fingerprint, compared against every photo
  in `known_faces/`. Faces are tracked between frames, so a name sticks even while the person turns away.
- **Saving CPU:** when the picture isn't changing and nobody is in view, faces are only checked once a second.
- **Zones and Origin:** ORB features and a homography match the current picture to a saved one, so the lines and the
  home position survive the camera turning.
- **App:** FastAPI server with a single-page web app. Live video is the camera's own H.265 stream (fragmented MP4 over a
  WebSocket into Media Source Extensions), falling back to JPEG frames on devices that can't play it.

## Privacy and security

- Secrets live in `config.json` and `go2rtc.yaml`, which are git-ignored and should never be committed.
- App passwords are stored as salted hashes, and login sessions only as token hashes.
- go2rtc only listens on `127.0.0.1`, because its page has no password and can show the Mi account token.
- Face recognition records people. Check local laws before pointing a camera at a public area or a neighbour's
  property, and make sure everyone in the household knows the camera is there.

## Credits

- [go2rtc](https://github.com/AlexxIT/go2rtc) for the camera streams
- [OpenCV Zoo](https://github.com/opencv/opencv_zoo) for the YuNet and SFace models
- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) and
  [YOLO11Face](https://github.com/zjykzj/YOLO11Face) for the detection models
- [Tailscale](https://tailscale.com) for remote access

Each of these has its own license.
