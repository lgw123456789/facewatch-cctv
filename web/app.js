"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const enc = encodeURIComponent;
const view = $("#view");
const bar = $("#bar");
const BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

const ICONS = {
  video: '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z"/><path d="m15 10.5 5.2-3.1a.5.5 0 0 1 .8.4v8.4a.5.5 0 0 1-.8.4L15 13.5"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.2 14.3A6.5 6.5 0 0 1 21.5 20"/>',
  bell: '<path d="M6 10a6 6 0 0 1 12 0c0 5 2 6.5 2 6.5H4S6 15 6 10"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevronRight: '<path d="m9 5 7 7-7 7"/>',
  chevronLeft: '<path d="m15 5-7 7 7 7"/>',
  chevronUp: '<path d="m5 15 7-7 7 7"/>',
  chevronDown: '<path d="m5 9 7 7 7-7"/>',
  camera: '<path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2.2L9.3 5h5.4l1.6 2h2.2A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><circle cx="12" cy="13" r="3.4"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 4.8-4.8a1 1 0 0 1 1.4 0L14 17l2-2a1 1 0 0 1 1.4 0L20 17.6"/>',
  scan: '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><path d="M9 10v1M15 10v1M9.5 15a3.5 3.5 0 0 0 5 0"/>',
  power: '<path d="M12 3.5v7.5"/><path d="M6.4 6.6a7.5 7.5 0 1 0 11.2 0"/>',
  expand: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  shrink: '<path d="M9 4v4a1 1 0 0 1-1 1H4M20 9h-4a1 1 0 0 1-1-1V4M15 20v-4a1 1 0 0 1 1-1h4M4 15h4a1 1 0 0 1 1 1v4"/>',
  origin: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.2"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22"/>',
  trash: '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l.9 11.2A2 2 0 0 0 9.4 20h5.2a2 2 0 0 0 2-1.8L17.5 7M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  flip: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 8.5-8.5M16 7l2.5 2.5M18.5 4.5 21 7"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M11 18.5h2"/>',
  zones: '<path d="M8 3.5 7 20.5M17 3.5l1 17"/><circle cx="8" cy="3.5" r="1.2"/><circle cx="17" cy="3.5" r="1.2"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  siren: '<path d="M6 18v-5a6 6 0 0 1 12 0v5M4 18h16v3H4zM12 3v2M4.2 6.2l1.4 1.4M19.8 6.2l-1.4 1.4"/>',
};

const ZONE_COLORS = { Outside: "rgba(90, 160, 255, .22)", Entrance: "rgba(242, 169, 59, .26)", Inside: "rgba(255, 77, 66, .26)" };

let me = null;
let cleanup = null;
let closeOverlay = null;
let freshPerson = null;
let toastTimer = null;

function icon(name, extra = "") {
  return `<svg class="i ${extra}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
}

function chevron() {
  return icon("chevronRight", "chev");
}

function tile(name) {
  return `<span class="tile">${icon(name)}</span>`;
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function avatar(name, cover, extra = "") {
  if (name === "Unknown") return `<span class="avatar unknown ${extra}">?</span>`;
  const img = cover
    ? `<img alt="" src="/api/people/${enc(name)}/avatar?v=${enc(cover)}" onerror="this.remove()">`
    : "";
  return `<span class="avatar ${extra}">${esc(name[0].toUpperCase())}${img}</span>`;
}

function nameTag(name) {
  if (name === "Unclear") return '<span class="name unclear">Not clear</span>';
  if (name === "Hidden") return '<span class="name hidden-face">Face hidden</span>';
  return `<span class="name ${name === "Unknown" ? "unknown" : ""}">${esc(name)}</span>`;
}

function warningTag(zone) {
  return zone ? `<span class="zone-tag">⚠ ${esc(zone)}</span>` : "";
}

// Where someone is, for the descriptions: "Outside", "Entrance" or "Inside", when zones are drawn.
function zoneNote(zone) {
  return zone ? ` · <span class="zone-${zone.toLowerCase()}">${esc(zone)}</span>` : "";
}

// The part of a picture on one side of a line (x1, y1, x2, y2); sign picks the side.
function clipToSide(polygon, line, sign) {
  const [x1, y1, x2, y2] = line;
  const side = p => sign * ((x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1));
  const out = [];
  polygon.forEach((p, i) => {
    const q = polygon[(i + 1) % polygon.length];
    const sp = side(p);
    const sq = side(q);
    if (sp >= 0) out.push(p);
    if ((sp >= 0) !== (sq >= 0)) {
      const t = sp / (sp - sq);
      out.push([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]);
    }
  });
  return out;
}

// The three areas the two lines make in a width x height picture, decided as on the laptop.
function zoneAreas(lines, width, height) {
  const [first, second] = lines;
  const sideOf = (line, p) => (line[2] - line[0]) * (p[1] - line[1]) - (line[3] - line[1]) * (p[0] - line[0]);
  const middle = line => [(line[0] + line[2]) / 2, (line[1] + line[3]) / 2];
  const towardsSecond = Math.sign(sideOf(first, middle(second))) || 1;
  const towardsFirst = Math.sign(sideOf(second, middle(first))) || 1;
  const picture = [[0, 0], [width, 0], [width, height], [0, height]];
  return {
    Outside: clipToSide(picture, first, -towardsSecond),
    Entrance: clipToSide(clipToSide(picture, first, towardsSecond), second, towardsFirst),
    Inside: clipToSide(picture, second, -towardsFirst),
  };
}

function toast(message, kind = "", ms = 3500) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = `toast ${kind}`; }, ms);
}

function fail(error) {
  if (!error.silent) toast(error.message, "error");
}

async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  let body;
  if (method !== "GET") headers["X-FaceWatch"] = "1";
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  if (form) body = form;

  let res;
  try {
    res = await fetch("/api" + path, { method, headers, body, credentials: "same-origin" });
  } catch {
    throw new Error("Can't reach FaceWatch. Check that the laptop is on and Tailscale is connected.");
  }
  const data = (res.headers.get("content-type") || "").includes("json") ? await res.json() : null;
  if (res.status === 401 && path !== "/login") {
    me = null;
    showLogin(false);
    throw Object.assign(new Error("Please sign in."), { silent: true });
  }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(Array.isArray(detail) ? "Please check what you entered." : detail || `Something went wrong (${res.status}).`);
  }
  return data;
}

function setBar({ title = "", back = null, actions = "", sub = false } = {}) {
  $("#bar-title").textContent = title;
  $("#bar-left").innerHTML = back
    ? `<a class="bar-btn" href="${back[0]}">${icon("chevronLeft")}<span>${esc(back[1])}</span></a>`
    : "";
  $("#bar-right").innerHTML = actions;
  bar.classList.toggle("sub", sub);
  onScroll();
}

function onScroll() {
  bar.classList.toggle("scrolled", window.scrollY > 36);
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function timeAgo(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function dayLabel(date) {
  const d = new Date(date + "T00:00:00");
  const diff = Math.round((new Date(new Date().toDateString()) - d) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

// Phone photos are 3-12 MB; shrinking them first makes uploads quick even on mobile data.
async function shrinkImage(file, maxSide = 1280) {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if (bitmap.close) bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.9));
    return blob || file;
  } catch {
    return file;
  }
}

// Browsers only allow the in-app camera on https:// addresses (e.g. Tailscale) and on the laptop itself.
function canUseCamera() {
  return window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// Talk: the microphone (with the phone's own noise and echo removal) goes over WebRTC to go2rtc's talk stream, which
// FaceWatch plays on the camera's speaker. Returns a function that hangs up.
async function startTalk(onState) {
  if (!canUseCamera() || !window.RTCPeerConnection) {
    throw new Error("Talking needs the https:// Tailscale address (or the laptop itself).");
  }
  let mic;
  try {
    mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, voiceIsolation: true, channelCount: 1 },
    });
  } catch {
    throw new Error("Allow the microphone to talk through the camera.");
  }
  const pc = new RTCPeerConnection();
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/stream?talk=1`);
  let ended = false;
  let session = null;
  let checkIn = null;
  const end = (failed, reason) => {
    if (ended) return;
    ended = true;
    clearTimeout(giveUp);
    clearInterval(checkIn);
    if (session) api("/talk/stop", { method: "POST", json: { talk: session } }).catch(() => {});
    mic.getTracks().forEach(track => track.stop());
    pc.close();
    ws.close();
    onState(failed ? "failed" : "off", reason);
  };
  // No connection after a while is almost always Windows Firewall blocking go2rtc on this network.
  const giveUp = setTimeout(() => end(true), 15000);
  const send = message => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(message));
  pc.addTransceiver(mic.getAudioTracks()[0], { direction: "sendonly" });
  pc.onicecandidate = event => send({ type: "webrtc/candidate", value: event.candidate ? event.candidate.candidate : "" });
  pc.onconnectionstatechange = async () => {
    if (pc.connectionState === "connected" && !session) {
      try {
        session = (await api("/talk/start", { method: "POST" })).talk;
      } catch (e) {
        return end(true, e.message);
      }
      if (ended) api("/talk/stop", { method: "POST", json: { talk: session } }).catch(() => {});
      else {
        clearTimeout(giveUp);
        // Without these the laptop ends Talk within seconds (page closed, signal lost).
        checkIn = setInterval(async () => {
          const { talking } = await api("/talk/alive", { method: "POST", json: { talk: session } }).catch(() => ({ talking: true }));
          if (!talking) end(true, "Talk ended. It stops by itself after 5 minutes; tap Talk to carry on.");
        }, 2000);
        onState("talking");
      }
    }
    if (pc.connectionState === "failed" || pc.connectionState === "disconnected") end(true);
  };
  ws.onopen = async () => {
    await pc.setLocalDescription(await pc.createOffer());
    send({ type: "webrtc/offer", value: pc.localDescription.sdp });
  };
  ws.onmessage = event => {
    if (typeof event.data !== "string") return;
    const message = JSON.parse(event.data);
    if (message.type === "webrtc/answer") pc.setRemoteDescription({ type: "answer", sdp: message.value }).catch(() => end(true));
    if (message.type === "webrtc/candidate" && message.value) pc.addIceCandidate({ candidate: message.value, sdpMid: "0" }).catch(() => {});
    if (message.type === "error") end(true, `go2rtc: ${message.value}`);
  };
  ws.onclose = () => end(!session);
  onState("connecting");
  return () => end(false);
}

function openSheet(html) {
  if (closeOverlay) closeOverlay();
  const backdrop = document.createElement("div");
  backdrop.className = "backdrop";
  const sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.innerHTML = `<div class="grabber"></div>${html}`;
  const close = () => {
    backdrop.remove();
    sheet.remove();
    if (closeOverlay === close) closeOverlay = null;
  };
  backdrop.onclick = close;
  sheet.addEventListener("click", event => {
    if (event.target.closest("[data-act=cancel]")) close();
  });
  document.body.append(backdrop, sheet);
  closeOverlay = close;
  return { sheet, close };
}

function testerControl() {
  return canUseCamera()
    ? `<button class="control" data-test-camera>${icon("scan")}Test</button>`
    : `<label class="control">${icon("scan")}Test<input type="file" accept="image/*" capture="user" data-test-photo></label>`;
}

function testerRow() {
  return canUseCamera()
    ? `<button class="row" data-test-camera>${tile("scan")}<span class="grow">Test recognition</span>${chevron()}</button>`
    : `<label class="row">${tile("scan")}<span class="grow">Test recognition with a photo</span>${chevron()}
         <input type="file" accept="image/*" capture="user" data-test-photo></label>`;
}

function wireTesterButton(root) {
  const button = root.querySelector("[data-test-camera]");
  if (button) button.onclick = () => openTester(null);
  const input = root.querySelector("[data-test-photo]");
  if (input) {
    input.onchange = () => {
      const file = input.files[0];
      input.value = "";
      if (file) openTester(file);
    };
  }
}

// Full-screen camera for adding photos. send(blob) uploads one and returns {kind, text}; onClose gets "done", "denied"
// or "failed". Returns a function that closes it.
function openCamera(send, onClose) {
  const box = document.createElement("div");
  box.className = "camera";
  box.innerHTML = `
    <video playsinline autoplay muted></video>
    <div class="camera-guide"></div>
    <div class="camera-top">
      <span id="camera-count">Take 3 to 5 photos</span>
      <button class="bar-btn" data-act="done">Done</button>
    </div>
    <div class="camera-msg" id="camera-msg">Line the face up with the oval</div>
    <div class="camera-bar">
      <button class="round" data-act="flip" aria-label="Switch camera">${icon("flip")}</button>
      <button class="shutter" data-act="shoot" aria-label="Take photo"></button>
      <span></span>
    </div>`;
  document.body.append(box);
  const video = box.querySelector("video");
  const message = box.querySelector("#camera-msg");
  let stream = null;
  let facing = "user";
  let busy = false;
  let added = 0;
  let closed = false;

  const stopStream = () => {
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
  };
  const close = reason => {
    if (closed) return;
    closed = true;
    stopStream();
    box.remove();
    if (reason) onClose(reason);
  };
  const start = async () => {
    stopStream();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 960 } },
      });
      if (closed) return stopStream();
      video.srcObject = stream;
      video.classList.toggle("mirror", facing === "user");
      await video.play().catch(() => {});
    } catch (e) {
      close(e.name === "NotAllowedError" || e.name === "SecurityError" ? "denied" : "failed");
    }
  };
  const shoot = async () => {
    if (busy || !video.videoWidth) return;
    busy = true;
    box.classList.add("flash");
    setTimeout(() => box.classList.remove("flash"), 120);
    const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.92));
    message.className = "camera-msg";
    message.textContent = "Checking…";
    const r = await send(blob);
    if (closed) return;
    message.className = `camera-msg ${r.kind}`;
    message.textContent = r.text;
    if (r.kind !== "bad") {
      added += 1;
      box.querySelector("#camera-count").textContent = `${plural(added, "photo")} added`;
    }
    busy = false;
  };

  box.onclick = event => {
    const act = event.target.closest("[data-act]")?.dataset.act;
    if (act === "done") close("done");
    if (act === "shoot") shoot();
    if (act === "flip") {
      facing = facing === "user" ? "environment" : "user";
      start();
    }
  };
  start();
  return () => close(null);
}

// What FaceWatch recognises through this device's camera (or in one photo). Nothing is saved or sent.
function openTester(file) {
  if (closeOverlay) closeOverlay();
  const live = !file;
  const box = document.createElement("div");
  box.className = "camera tester";
  box.innerHTML = `
    ${live ? "<video playsinline autoplay muted></video>" : "<img alt='Test photo'>"}
    <canvas class="boxes"></canvas>
    <div class="camera-top">
      <span>Recognition test</span>
      <button class="bar-btn" data-act="close">Close</button>
    </div>
    <div class="tester-panel">
      <div class="names" id="tester-faces"><span class="dim">Loading face recognition…</span></div>
      <div class="note">Test only. Nothing is saved or sent.</div>
    </div>
    <div class="camera-bar">
      <span></span>
      ${live
        ? `<button class="round" data-act="flip" aria-label="Switch camera">${icon("flip")}</button>`
        : `<label class="btn pill">${icon("camera")}Take Another<input type="file" accept="image/*" capture="user" data-test-photo></label>`}
      <span></span>
    </div>`;
  document.body.append(box);
  const media = box.querySelector(live ? "video" : "img");
  const canvas = box.querySelector(".boxes");
  const facesBox = box.querySelector("#tester-faces");
  let stream = null;
  let facing = "user";
  let closed = false;
  let last = null;

  const draw = () => drawFaces(canvas, last, last ? last.faces : [], live && facing === "user");

  const show = result => {
    last = result;
    facesBox.innerHTML = result.faces.length
      ? result.faces.map(f => (f.name === "Unclear"
        ? `${nameTag(f.name)}<span class="dim">turn towards the camera</span>`
        : `${nameTag(f.name)}<span class="dim num">${f.score.toFixed(2)}</span>`)).join("")
      : '<span class="dim">No face found. Face the camera in good light.</span>';
    draw();
  };

  const recognise = blob => {
    const form = new FormData();
    form.append("photo", blob, "test.jpg");
    return api("/test/recognise", { method: "POST", form });
  };

  const close = () => {
    if (closed) return;
    closed = true;
    if (stream) stream.getTracks().forEach(track => track.stop());
    window.removeEventListener("resize", draw);
    box.remove();
    if (closeOverlay === close) closeOverlay = null;
  };
  closeOverlay = close;
  window.addEventListener("resize", draw);

  const startCamera = async () => {
    if (stream) stream.getTracks().forEach(track => track.stop());
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      if (closed) return stream.getTracks().forEach(track => track.stop());
      media.srcObject = stream;
      media.classList.toggle("mirror", facing === "user");
      await media.play().catch(() => {});
    } catch (e) {
      close();
      toast(e.name === "NotAllowedError" ? "Camera access is blocked for this site. Allow it in your browser settings."
                                         : "Couldn't open the camera.", "error");
    }
  };

  // Sends one small frame at a time and waits for the answer, so it never falls behind.
  const loop = async () => {
    const grab = document.createElement("canvas");
    while (!closed) {
      if (!document.hidden && media.videoWidth) {
        const scale = Math.min(1, 640 / Math.max(media.videoWidth, media.videoHeight));
        grab.width = Math.round(media.videoWidth * scale);
        grab.height = Math.round(media.videoHeight * scale);
        grab.getContext("2d").drawImage(media, 0, 0, grab.width, grab.height);
        const blob = await new Promise(resolve => grab.toBlob(resolve, "image/jpeg", 0.85));
        try {
          const result = await recognise(blob);
          if (!closed) show(result);
        } catch (e) {
          if (!closed) facesBox.innerHTML = `<span class="dim">${esc(e.message)}</span>`;
          await new Promise(r => setTimeout(r, 2000));
        }
      }
      await new Promise(r => setTimeout(r, 300));
    }
  };

  const testPhoto = async photo => {
    last = null;
    draw();
    facesBox.innerHTML = '<span class="dim">Checking…</span>';
    const small = await shrinkImage(photo, 640);
    media.src = URL.createObjectURL(small);
    try {
      show(await recognise(small));
    } catch (e) {
      facesBox.innerHTML = `<span class="dim">${esc(e.message)}</span>`;
    }
  };

  box.onclick = event => {
    const act = event.target.closest("[data-act]")?.dataset.act;
    if (act === "close") close();
    if (act === "flip") {
      facing = facing === "user" ? "environment" : "user";
      last = null;
      draw();
      startCamera();
    }
  };
  if (live) {
    startCamera();
    loop();
  } else {
    const again = box.querySelector("[data-test-photo]");
    again.onchange = () => {
      const next = again.files[0];
      again.value = "";
      if (next) testPhoto(next);
    };
    testPhoto(file);
  }
}

const CAMERA_CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0"];

function playableCodecs() {
  const MediaSourceType = window.ManagedMediaSource || window.MediaSource;
  return MediaSourceType ? CAMERA_CODECS.filter(c => MediaSourceType.isTypeSupported(`video/mp4; codecs="${c}"`)) : [];
}

function canPlayCameraVideo() {
  return playableCodecs().length > 0;
}

// Plays the camera's own video with the device's video chip. onEnd(hadVideo) runs when it stops by itself (hadVideo is
// false if this device can't play it). Returns a function that stops it.
function playCameraVideo(video, onEnd) {
  const source = new (window.ManagedMediaSource || window.MediaSource)();
  let socket = null;
  let buffer = null;
  let ended = false;
  let hadVideo = false;
  const queue = [];

  const stop = () => {
    if (ended) return;
    ended = true;
    clearTimeout(watchdog);
    clearInterval(health);
    if (socket) socket.close();
    // While it reconnects, the last picture stays on screen instead of a black box.
    try {
      const still = document.createElement("canvas");
      still.width = video.videoWidth / 2;
      still.height = video.videoHeight / 2;
      still.getContext("2d").drawImage(video, 0, 0, still.width, still.height);
      if (still.width) video.poster = still.toDataURL("image/jpeg", 0.7);
    } catch {}
    video.removeAttribute("src");
    video.load();
  };
  const finish = () => {
    if (ended) return;
    stop();
    onEnd(hadVideo);
  };
  const watchdog = setTimeout(() => { if (!hadVideo) finish(); }, 10000);
  // After a pause (weak connection, go2rtc's own camera link dropping) skip the gap; start again if it stops for good.
  let lastTime = -1;
  let stuck = 0;
  const health = setInterval(() => {
    if (!hadVideo || document.hidden) return;
    stuck = video.currentTime === lastTime ? stuck + 1 : 0;
    lastTime = video.currentTime;
    const ranges = video.buffered;
    if (stuck >= 2 && ranges.length && ranges.end(ranges.length - 1) - video.currentTime > 0.2) {
      video.currentTime = ranges.end(ranges.length - 1) - 0.1;
      stuck = 0;
    }
    if (stuck >= 8) finish();
    if (video.paused) video.play().catch(() => {});
  }, 1000);
  const pump = () => {
    if (ended || !buffer || buffer.updating) return;
    const ranges = video.buffered;
    if (ranges.length) {
      // Stay within a quarter of a second of live.
      const lag = ranges.end(ranges.length - 1) - video.currentTime;
      if (lag > 0.8) video.currentTime = ranges.end(ranges.length - 1) - 0.1;
      video.playbackRate = lag > 0.25 ? 1.15 : 1;
      if (video.currentTime - ranges.start(0) > 30) {
        buffer.remove(ranges.start(0), video.currentTime - 10);
        return;
      }
    }
    if (queue.length) {
      try { buffer.appendBuffer(queue.shift()); } catch { finish(); }
    }
  };

  video.onerror = finish;
  if (window.ManagedMediaSource) video.disableRemotePlayback = true;
  source.addEventListener("sourceopen", () => {
    socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/stream`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => socket.send(JSON.stringify({ type: "mse", value: playableCodecs().join(",") }));
    socket.onclose = finish;
    socket.onmessage = event => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data);
        if (message.type === "mse") {
          try {
            buffer = source.addSourceBuffer(message.value);
            buffer.mode = "segments";
            buffer.addEventListener("updateend", pump);
          } catch { finish(); }
        } else if (message.type === "error") {
          finish();
        }
        return;
      }
      hadVideo = true;
      queue.push(event.data);
      pump();
      if (video.paused) video.play().catch(() => {});
    };
  }, { once: true });
  video.src = URL.createObjectURL(source);
  return stop;
}

// For devices that can't play the video: the newest picture, the next one only after the last arrived.
function showPictures(img) {
  let ended = false;
  let timer = null;
  const next = () => { if (!ended) img.src = `/api/live.jpg?t=${Date.now()}`; };
  img.onload = () => { timer = setTimeout(next, 100); };
  img.onerror = () => { timer = setTimeout(next, 1000); };
  next();
  return () => {
    ended = true;
    clearTimeout(timer);
    img.onload = img.onerror = null;
    img.src = BLANK;
  };
}

// Draws name boxes over a picture shown letterboxed ("contain"). frame is the size the boxes were measured in.
function drawFaces(canvas, frame, faces, mirrored = false, lines = null) {
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(cw * dpr);
  canvas.height = Math.round(ch * dpr);
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, cw, ch);
  if (!frame) return;
  const scale = Math.min(cw / frame.width, ch / frame.height);
  const ox = (cw - frame.width * scale) / 2;
  const oy = (ch - frame.height * scale) / 2;
  if (lines) {
    g.lineWidth = 2;
    g.strokeStyle = "rgba(255, 77, 66, .8)";
    for (const [x1, y1, x2, y2] of lines) {
      g.beginPath();
      g.moveTo(ox + x1 * scale, oy + y1 * scale);
      g.lineTo(ox + x2 * scale, oy + y2 * scale);
      g.stroke();
    }
  }
  if (!faces || !faces.length) return;
  const box = (x, y, w, h, r) => {
    g.beginPath();
    if (g.roundRect) g.roundRect(x, y, w, h, r);
    else g.rect(x, y, w, h);
  };
  g.font = "600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  for (const f of faces) {
    const [x, y, w, h] = f.box;
    const X = ox + (mirrored ? frame.width - x - w : x) * scale;
    const Y = oy + y * scale;
    const hidden = f.name === "Hidden";
    const color = f.name === "Unknown" ? "#ff4d42" : f.name === "Unclear" ? "#a2a2a8" : hidden ? "#f2a93b" : "#32d167";
    g.lineWidth = 2.5;
    g.strokeStyle = color;
    g.setLineDash(hidden ? [8, 6] : []);
    box(X, Y, w * scale, h * scale, 8);
    g.stroke();
    g.setLineDash([]);
    const label = f.name === "Unclear" ? "Not clear" : hidden ? "Face hidden" : `${f.name}  ${f.score.toFixed(2)}`;
    const labelY = Math.max(0, Y - 24);
    g.fillStyle = color;
    box(X, labelY, g.measureText(label).width + 12, 20, 6);
    g.fill();
    g.fillStyle = "#0c0c0d";
    g.fillText(label, X + 6, labelY + 14.5);
  }
}

// The gate and front-door lines from the first drawing, used until zones are saved.
const DEFAULT_ZONE_LINES = [[0.517, 0.435, 0.517, 1], [0.85, 0.511, 0.891, 0.974]];

async function renderZones() {
  setBar({ title: "Zones", back: ["#/settings", "Settings"], sub: true });
  view.innerHTML = `
    <div class="video zone-editor" id="zone-box">
      <img id="zone-picture" alt="Camera picture">
      <canvas class="boxes" id="zone-canvas"></canvas>
      <div class="video-state" id="zone-state"><div class="spinner"></div><div id="zone-state-text">Getting a picture from the camera…</div></div>
    </div>
    <div class="group-note">Drag the dots so each line lies on the floor. <b>Line 1</b> (the gate) separates Outside from the
      Entrance, and <b>line 2</b> (the front door) separates the Entrance from Inside. Saving also keeps this picture, so
      FaceWatch can find the lines again if the camera turns.</div>
    <div class="zone-actions">
      <button class="btn" id="zone-save" disabled>Save</button>
      <button class="btn secondary" id="zone-refresh">New Picture</button>
    </div>
    <div class="group" style="margin-top:20px"><button class="row danger" id="zone-remove">Remove Zones</button></div>`;
  const img = $("#zone-picture");
  const canvas = $("#zone-canvas");
  let lines = DEFAULT_ZONE_LINES.map(line => [...line]);
  let drag = null;
  let pictureUrl = null;
  try {
    const saved = await api("/zones");
    if (saved.lines) lines = saved.lines.map(line => [...line]);
  } catch (e) { return fail(e); }

  // Where the letterboxed picture sits inside the box.
  const layout = () => {
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const scale = Math.min(cw / (img.naturalWidth || 16), ch / (img.naturalHeight || 9));
    const w = (img.naturalWidth || 16) * scale;
    const h = (img.naturalHeight || 9) * scale;
    return { cw, ch, w, h, x: (cw - w) / 2, y: (ch - h) / 2 };
  };
  const draw = () => {
    const L = layout();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(L.cw * dpr);
    canvas.height = Math.round(L.ch * dpr);
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, L.cw, L.ch);
    if (!img.naturalWidth) return;
    const at = ([px, py]) => [L.x + px * L.w, L.y + py * L.h];
    g.font = "700 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    g.textAlign = "center";
    for (const [name, area] of Object.entries(zoneAreas(lines, 1, 1))) {
      if (area.length < 3) continue;
      g.fillStyle = ZONE_COLORS[name];
      g.beginPath();
      area.map(at).forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
      g.closePath();
      g.fill();
      const [x, y] = at([area.reduce((a, p) => a + p[0], 0) / area.length, area.reduce((a, p) => a + p[1], 0) / area.length]);
      g.fillStyle = "#fff";
      g.fillText(name, x, y);
    }
    lines.forEach((line, i) => {
      const [a, b] = [at(line.slice(0, 2)), at(line.slice(2))];
      g.lineWidth = 3;
      g.strokeStyle = "#ff4d42";
      g.beginPath();
      g.moveTo(...a);
      g.lineTo(...b);
      g.stroke();
      for (const [x, y] of [a, b]) {
        g.beginPath();
        g.arc(x, y, 9, 0, Math.PI * 2);
        g.fillStyle = "#fff";
        g.fill();
        g.stroke();
      }
      g.fillStyle = "#ff4d42";
      g.fillText(String(i + 1), (a[0] + b[0]) / 2 + 14, (a[1] + b[1]) / 2);
    });
  };
  const toPicture = event => {
    const rect = canvas.getBoundingClientRect();
    const L = layout();
    return [(event.clientX - rect.left - L.x) / L.w, (event.clientY - rect.top - L.y) / L.h];
  };
  canvas.addEventListener("pointerdown", event => {
    if (!img.naturalWidth) return;
    const L = layout();
    const [px, py] = toPicture(event);
    let nearest = 32;
    lines.forEach((line, i) => [0, 2].forEach(k => {
      const distance = Math.hypot((line[k] - px) * L.w, (line[k + 1] - py) * L.h);
      if (distance < nearest) [nearest, drag] = [distance, [i, k]];
    }));
    if (drag) canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!drag) return;
    const [px, py] = toPicture(event).map(v => Math.min(1, Math.max(0, v)));
    lines[drag[0]][drag[1]] = px;
    lines[drag[0]][drag[1] + 1] = py;
    draw();
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  const loadPicture = async () => {
    $("#zone-state").classList.remove("hidden");
    $("#zone-state-text").textContent = "Getting a picture from the camera…";
    $("#zone-save").disabled = true;
    try { await api("/camera/start", { method: "POST" }); } catch (e) { return fail(e); }
    for (let i = 0; i < 60 && location.hash === "#/zones"; i++) {
      const res = await fetch(`/api/live.jpg?t=${Date.now()}`, { credentials: "same-origin" });
      if (res.ok) {
        if (pictureUrl) URL.revokeObjectURL(pictureUrl);
        pictureUrl = URL.createObjectURL(await res.blob());
        await new Promise(resolve => { img.onload = img.onerror = resolve; img.src = pictureUrl; });
        $("#zone-state").classList.add("hidden");
        $("#zone-save").disabled = false;
        draw();
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    $("#zone-state-text").textContent = "Couldn't get a picture. Check the camera on the Live page.";
  };

  $("#zone-save").onclick = async () => {
    try {
      await api("/zones", { method: "PUT", json: { lines } });
      toast("Zones saved");
      go("#/settings");
    } catch (e) { fail(e); }
  };
  $("#zone-refresh").onclick = loadPicture;
  $("#zone-remove").onclick = async () => {
    if (!confirm("Remove the zone lines? Zone warnings stop until you draw them again.")) return;
    try {
      await api("/zones", { method: "DELETE" });
      toast("Zones removed");
      go("#/settings");
    } catch (e) { fail(e); }
  };
  window.addEventListener("resize", draw);
  cleanup = () => {
    window.removeEventListener("resize", draw);
    if (pictureUrl) URL.revokeObjectURL(pictureUrl);
  };
  loadPicture();
}

const routes = [
  [/^#\/live$/, renderLive],
  [/^#\/zones$/, renderZones],
  [/^#\/people$/, renderPeople],
  [/^#\/people\/new$/, renderNewPerson],
  [/^#\/people\/([^/]+)$/, m => renderPerson(decodeURIComponent(m[1]))],
  [/^#\/alerts$/, renderAlerts],
  [/^#\/settings$/, renderSettings],
];

async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  if (closeOverlay) closeOverlay();
  if (!me) return;
  const hash = location.hash || "#/live";
  for (const [pattern, render] of routes) {
    const match = hash.match(pattern);
    if (!match) continue;
    document.querySelectorAll(".tabs a").forEach(a => a.classList.toggle("active", hash.startsWith(a.getAttribute("href"))));
    window.scrollTo(0, 0);
    try { await render(match); } catch (e) { fail(e); }
    return;
  }
  go("#/live");
}

function showLogin(needsSetup) {
  if (cleanup) { cleanup(); cleanup = null; }
  if (closeOverlay) closeOverlay();
  document.body.classList.add("auth");
  setBar();
  view.innerHTML = `
    <form class="login" id="login">
      <img class="mark" src="/icons/icon-192.png" alt="">
      <h1>FaceWatch</h1>
      <p>${needsSetup ? "Create the first login for this camera." : "Sign in to your camera."}</p>
      <div class="group">
        <input class="field" name="username" placeholder="Username" autocomplete="username"
          autocapitalize="none" autocorrect="off" spellcheck="false" required>
        <input class="field" name="password" type="password" placeholder="Password"
          autocomplete="${needsSetup ? "new-password" : "current-password"}" required>
        ${needsSetup ? '<input class="field" name="repeat" type="password" placeholder="Repeat password" autocomplete="new-password" required>' : ""}
      </div>
      ${needsSetup ? '<div class="group-note">At least 8 characters. You can add logins for the rest of the household later.</div>' : ""}
      <button class="btn">${needsSetup ? "Create Login" : "Sign In"}</button>
    </form>`;
  $("#login").onsubmit = async event => {
    event.preventDefault();
    const f = event.target.elements;
    if (needsSetup && f.password.value !== f.repeat.value) return toast("The passwords don't match.", "error");
    try {
      const r = await api(needsSetup ? "/setup" : "/login", {
        method: "POST", json: { username: f.username.value.trim(), password: f.password.value },
      });
      me = r.user;
      document.body.classList.remove("auth");
      go("#/live");
    } catch (e) { fail(e); }
  };
}

function renderLive() {
  setBar({ title: "Live" });
  view.innerHTML = `
    <h1 class="large-title" id="camera-name">Live</h1>
    <div class="status"><span class="dot busy" id="status-dot"></span><span id="status-text">Starting…</span></div>
    <div class="video" id="video">
      <video id="player" class="hidden" muted playsinline autoplay></video>
      <img id="picture" class="hidden" alt="Live camera view">
      <canvas class="boxes" id="boxes"></canvas>
      <div class="video-state" id="video-state"><div class="spinner" id="spinner"></div><div id="video-state-text">Starting the camera…</div></div>
      <span class="live-badge hidden" id="live-badge">LIVE</span>
      <div class="pan hidden" id="pan" role="group" aria-label="Turn the camera">
        <button class="pan-btn" data-turn="up" aria-label="Turn up">${icon("chevronUp")}</button>
        <button class="pan-btn" data-turn="left" aria-label="Turn left">${icon("chevronLeft")}</button>
        <button class="pan-btn" data-turn="right" aria-label="Turn right">${icon("chevronRight")}</button>
        <button class="pan-btn" data-turn="down" aria-label="Turn down">${icon("chevronDown")}</button>
      </div>
      <button class="video-btn" id="fullscreen" aria-label="Full screen">${icon("expand")}</button>
    </div>
    <div class="zone-note hidden" id="outdated">FaceWatch was updated on the laptop. Close its window and start it again
      (start.bat) to use the new version; until then some buttons may not work.</div>
    <div class="zone-note hidden" id="zone-note">Zones are paused: the camera has turned too far to find your lines.
      Turn it back, or draw them again in Settings → Zones.</div>
    <button class="btn alarm-stop hidden" id="stop-alarm">${icon("siren")}Stop the Alarm</button>
    <div class="controls">
      <button class="control hidden" id="origin">${icon("origin")}<span id="origin-label">Origin</span></button>
      <button class="control hidden" id="talk">${icon("mic")}<span id="talk-label">Talk</span></button>
      ${testerControl()}
      <button class="control stop" id="power">${icon("power")}<span id="power-label">Turn off</span></button>
    </div>
    <button class="link-btn hidden" id="set-origin">Set this view as the origin</button>
    <label class="group talk-volume hidden" id="talk-volume">
      <div class="row"><span>Speaker volume</span><input type="range" min="0" max="100" step="5"><span class="num">70%</span></div>
    </label>
    <div class="group-label">In view</div>
    <div class="group avatars" id="inview"><div class="row muted">Nobody</div></div>
    <div class="group-label">Last recorded</div>
    <a class="group" href="#/alerts"><div class="row" id="last"><span class="grow dim">Nothing since the camera was turned on</span>${chevron()}</div></a>`;
  wireTesterButton(view);

  const box = $("#video");
  const player = $("#player");
  const picture = $("#picture");
  const boxes = $("#boxes");
  const covers = {};
  let stopped = false;
  let stopVideo = null;
  let hangUp = null;
  let cameraState = "starting";
  let lastStatus = null;
  let useVideo = true;
  api("/people").then(people => people.forEach(p => { covers[p.name] = p.cover; })).catch(() => {});

  const redraw = () => {
    const s = lastStatus;
    const shown = s ? [...s.hidden.map(p => ({ ...p, name: "Hidden" })), ...s.in_view] : [];
    drawFaces(boxes, s && s.frame ? { width: s.frame[0], height: s.frame[1] } : null, shown, false, s && s.zones.lines);
  };
  const startVideo = () => {
    if (stopped || document.hidden || stopVideo) return;
    // The camera's own video when the phone can play it; otherwise the newest picture, one at a time.
    if (useVideo && lastStatus && lastStatus.video === "go2rtc" && canPlayCameraVideo()) {
      player.classList.remove("hidden");
      picture.classList.add("hidden");
      stopVideo = playCameraVideo(player, hadVideo => {
        stopVideo = null;
        if (!hadVideo) useVideo = false;
        if (cameraState === "on") setTimeout(startVideo, hadVideo ? 1000 : 0);
      });
    } else {
      picture.classList.remove("hidden");
      player.classList.add("hidden");
      stopVideo = showPictures(picture);
    }
  };
  const endVideo = () => {
    if (stopVideo) stopVideo();
    stopVideo = null;
  };
  // The buttons on the video turn faint after a few seconds (they still work).
  let idleTimer = null;
  let held = null;
  const wake = () => {
    box.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { if (!held) box.classList.add("idle"); }, 3000);
  };
  box.addEventListener("pointerdown", wake);
  box.addEventListener("pointermove", event => { if (event.pointerType === "mouse") wake(); });
  wake();

  // Full screen where the browser allows it (computers, Android, iPad); on iPhone the video fills the page.
  const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement;
  const setFull = async on => {
    box.classList.toggle("full", on);
    document.body.classList.toggle("watching", on);
    $("#fullscreen").innerHTML = icon(on ? "shrink" : "expand");
    $("#fullscreen").setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
    try {
      if (on && !fullscreenElement()) await (box.requestFullscreen || box.webkitRequestFullscreen)?.call(box);
      if (!on && fullscreenElement()) await (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
      if (on) await screen.orientation.lock("landscape");
    } catch {
      // Not allowed here: the page-sized view is used.
    }
    wake();
    setTimeout(redraw, 60);
  };
  $("#fullscreen").onclick = () => setFull(!box.classList.contains("full"));
  const onFullscreenChange = () => {
    if (!fullscreenElement() && box.classList.contains("full")) setFull(false);  // left with Esc or the back gesture
  };
  document.addEventListener("fullscreenchange", onFullscreenChange);
  document.addEventListener("webkitfullscreenchange", onFullscreenChange);
  window.addEventListener("resize", redraw);
  // Phones pause hidden pages; stop downloading video meanwhile and pick up again when the app comes back.
  const onVisibility = () => (document.hidden ? endVideo() : cameraState === "on" && startVideo());
  document.addEventListener("visibilitychange", onVisibility);

  const update = s => {
    if (stopped) return;
    lastStatus = s;
    cameraState = s.camera.state;
    const on = cameraState === "on";
    const showing = on && s.connected;
    if (showing && !stopVideo) startVideo();
    if (!on && stopVideo) endVideo();
    redraw();
    $("#camera-name").textContent = s.camera_name;
    $("#video-state").classList.toggle("hidden", showing);
    $("#video-state").classList.toggle("error", cameraState === "error");
    $("#spinner").classList.toggle("hidden", cameraState !== "starting" && !on);
    $("#video-state-text").textContent = s.camera.message;
    $("#live-badge").classList.toggle("hidden", !showing);
    $("#zone-note").classList.toggle("hidden", !(showing && s.zones.state === "lost"));
    $("#outdated").classList.toggle("hidden", !s.outdated);
    $("#talk").classList.toggle("hidden", !(showing && s.video === "go2rtc" && s.speaker));
    $("#stop-alarm").classList.toggle("hidden", !s.alarm);
    for (const id of ["#pan", "#origin", "#set-origin"]) $(id).classList.toggle("hidden", !(showing && s.turn));
    if ((!showing || !s.speaker) && hangUp) hangUp();
    $("#status-dot").className = `dot ${showing ? "live" : cameraState === "starting" || on ? "busy" : ""}`;
    $("#status-text").textContent = showing ? "Live" : cameraState === "off" ? "Camera off" : s.camera.message;
    const running = on || cameraState === "starting";
    $("#power-label").textContent = running ? "Turn off" : "Turn on";
    $("#power").classList.toggle("stop", running);
  };

  let shownInView = "";
  let shownLast = "";
  // Only touches the page when something changed, so profile pictures aren't reloaded every second.
  const showDetails = s => {
    const hiddenRows = s.hidden.map(h => {
      const detail = s.hidden_seconds
        ? `${Math.floor(s.hidden_seconds)} of ${s.hidden_alert_after} s before an alert${zoneNote(h.zone)}
           <div class="meter amber"><div style="width:${Math.min(100, (s.hidden_seconds / s.hidden_alert_after) * 100)}%"></div></div>`
        : `Their face can't be seen${zoneNote(h.zone)}`;
      return `<div class="row"><span class="avatar hidden-face">?</span>
        <div class="grow"><div class="title">Someone, face hidden</div><div class="detail">${detail}</div></div></div>`;
    });
    const inView = s.in_view.length || s.hidden.length
      ? hiddenRows.join("") + s.in_view.map(f => {
        if (f.name === "Unclear") {
          return `<div class="row"><span class="avatar">?</span>
            <div class="grow"><div class="title">Someone</div><div class="detail">Face not clear enough to tell yet${zoneNote(f.zone)}</div></div></div>`;
        }
        const unknown = f.name === "Unknown";
        const past = f.zone === "Entrance" ? "first" : f.zone === "Inside" ? "second" : null;
        const detail = unknown && past
          ? `<span class="zone-warn">⚠ Warning: past the ${past} line (${esc(f.zone)})</span>`
          : unknown && s.unknown_seconds
          ? `${Math.floor(s.unknown_seconds)} of ${s.unknown_alert_after} s before an alert${zoneNote(f.zone)}
             <div class="meter"><div style="width:${Math.min(100, (s.unknown_seconds / s.unknown_alert_after) * 100)}%"></div></div>`
          : `${unknown ? "Not anyone you've added" : "Recognised"}${zoneNote(f.zone)}`;
        return `<div class="row">${avatar(f.name, covers[f.name])}
          <div class="grow"><div class="title">${unknown ? "Unknown person" : esc(f.name)}</div><div class="detail">${detail}</div></div>
          <span class="value num">${f.score.toFixed(2)}</span></div>`;
      }).join("")
      : '<div class="row muted">Nobody</div>';
    if (inView !== shownInView) $("#inview").innerHTML = shownInView = inView;
    if (s.last_alert) {
      const last = `<div class="grow"><div class="names">${warningTag(s.last_alert.warning)}${s.last_alert.names.map(nameTag).join("")}</div>
        <div class="detail">${timeAgo(s.last_alert.time)}</div></div>${chevron()}`;
      if (last !== shownLast) $("#last").innerHTML = shownLast = last;
    }
  };

  const turnOn = async () => {
    try { update(await api("/camera/start", { method: "POST" })); } catch (e) { fail(e); }
  };

  // Tap to talk, tap again to stop (holding would cut off the first words while the call sets up).
  const talk = $("#talk");
  const showTalk = (state, reason) => {
    talk.classList.toggle("stop", state !== "off" && state !== "failed");
    $("#talk-label").textContent = { connecting: "Connecting…", talking: "Stop talking" }[state] || "Talk";
    $("#talk-volume").classList.toggle("hidden", state !== "talking");
    if (state === "talking") toast("Speak now: you're on the camera's speaker.", "", 2500);
    if (state === "failed") {
      toast(reason || "Couldn't reach the camera's speaker. Away from home, Windows Firewall must allow go2rtc on Private networks.",
        "error", 6000);
    }
    if (state === "off" || state === "failed") hangUp = null;
  };
  talk.onclick = async () => {
    if (hangUp) return hangUp();
    try {
      hangUp = await startTalk(showTalk);
      const { talk_volume: volume } = await api("/settings");
      $("#talk-volume input").value = volume;
      $("#talk-volume .num").textContent = `${volume}%`;
    } catch (e) {
      fail(e);
    }
  };
  $("#talk-volume input").oninput = e => { $("#talk-volume .num").textContent = `${e.target.value}%`; };
  $("#talk-volume input").onchange = e => {
    api("/settings", { method: "PUT", json: { talk_volume: Number(e.target.value) } }).catch(fail);
  };
  $("#stop-alarm").onclick = async () => {
    try {
      await api("/sound/stop", { method: "POST" });
      $("#stop-alarm").classList.add("hidden");
    } catch (e) { fail(e); }
  };
  // Tap for one step, hold to keep turning: the laptop steps while the app says "still holding" every 0.4 s.
  const press = button => {
    if (held) release();
    const direction = button.dataset.turn;
    const mine = { button };
    held = mine;
    button.classList.add("on");
    const move = () => api("/camera/move", { method: "POST", json: { direction } });
    mine.first = move().catch(e => {
      if (held === mine) release();
      fail(e);
    });
    mine.timer = setInterval(() => move().catch(() => {}), 400);
  };
  const release = () => {
    if (!held) return;
    const { button, timer, first } = held;
    held = null;
    clearInterval(timer);
    button.classList.remove("on");
    wake();
    // After the first step has gone, so a quick tap still turns one step.
    first.finally(() => api("/camera/move", { method: "POST", json: { direction: "stop" } }).catch(() => {}));
  };
  const arrows = Object.fromEntries([...$("#pan").querySelectorAll("[data-turn]")].map(b => [b.dataset.turn, b]));
  for (const button of Object.values(arrows)) {
    button.addEventListener("pointerdown", event => {
      if (event.button) return;
      event.preventDefault();
      try {
        button.setPointerCapture(event.pointerId);  // so letting go anywhere counts as letting go
      } catch {
        // Not supported: pointerup on the button still ends it.
      }
      press(button);
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) button.addEventListener(type, release);
    button.addEventListener("contextmenu", event => event.preventDefault());
  }
  // On a computer the arrow keys turn the camera too, and Esc leaves full screen.
  const keys = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  const onKey = event => {
    if (event.target.closest?.("input, textarea, select") || document.querySelector(".sheet, .viewer, .camera")) return;
    if (event.key === "Escape" && box.classList.contains("full")) return setFull(false);
    const button = arrows[keys[event.key]];
    if (!button || $("#pan").classList.contains("hidden")) return;
    event.preventDefault();
    if (event.type === "keydown" && !event.repeat && held?.button !== button) {
      wake();
      press(button);
    }
    if (event.type === "keyup" && held?.button === button) release();
  };
  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKey);

  // Origin turns the camera back (tap again to stop).
  const originButton = $("#origin");
  originButton.onclick = async () => {
    if (originButton.classList.contains("busy")) {
      api("/camera/move", { method: "POST", json: { direction: "stop" } }).catch(() => {});
      return;
    }
    originButton.classList.add("busy");
    $("#origin-label").textContent = "Returning…";
    try {
      const { message } = await api("/camera/origin", { method: "POST" });
      if (!stopped) toast(message, "", 2600);
    } catch (e) {
      fail(e);
    }
    originButton.classList.remove("busy");
    $("#origin-label").textContent = "Origin";
  };
  $("#set-origin").onclick = async () => {
    if (!confirm("Make the camera's current view its origin? Origin will always bring it back here.")) return;
    try {
      await api("/camera/origin", { method: "PUT" });
      toast("Origin saved", "", 1800);
    } catch (e) { fail(e); }
  };
  $("#power").onclick = async () => {
    if (cameraState === "off" || cameraState === "error") return turnOn();
    if (!confirm("Turn the camera off? Alerts stop until someone opens Live again.")) return;
    try { update(await api("/camera/stop", { method: "POST" })); } catch (e) { fail(e); }
  };

  // Twice a second while someone is in view, otherwise once; nothing while the app is in the background.
  let timer = null;
  const poll = async () => {
    if (stopped) return;
    if (!document.hidden) {
      try {
        const s = await api("/status");
        if (stopped) return;
        update(s);
        showDetails(s);
      } catch (e) {
        if (!stopped && !e.silent) $("#video-state-text").textContent = e.message;
      }
    }
    const someone = lastStatus && (lastStatus.in_view.length || lastStatus.hidden.length);
    if (!stopped) timer = setTimeout(poll, someone ? 500 : 1000);
  };
  turnOn().then(poll);

  cleanup = () => {
    stopped = true;
    release();
    clearTimeout(timer);
    clearTimeout(idleTimer);
    document.removeEventListener("visibilitychange", onVisibility);
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("keyup", onKey);
    document.removeEventListener("fullscreenchange", onFullscreenChange);
    document.removeEventListener("webkitfullscreenchange", onFullscreenChange);
    if (box.classList.contains("full")) setFull(false);
    window.removeEventListener("resize", redraw);
    endVideo();
    if (hangUp) hangUp();
  };
}

async function renderPeople() {
  setBar({ title: "People", actions: `<a class="bar-btn" href="#/people/new" aria-label="Add person">${icon("plus")}</a>` });
  view.innerHTML = `
    <h1 class="large-title">People</h1>
    <div class="group icons">${testerRow()}</div>
    <div id="people-list"><div class="loading"><div class="spinner"></div></div></div>`;
  wireTesterButton(view);
  const box = $("#people-list");
  const people = await api("/people");
  if (!box.isConnected) return;
  box.innerHTML = people.length
    ? `<div class="group-label">${people.length === 1 ? "1 person" : `${people.length} people`}</div>
      <div class="group avatars">${people.map(p => `
        <a class="row" href="#/people/${enc(p.name)}">${avatar(p.name, p.cover)}
          <div class="grow"><div class="title">${esc(p.name)}</div>
            <div class="detail">${p.photo_count ? plural(p.photo_count, "photo") : "No photos yet"}</div></div>
          ${chevron()}</a>`).join("")}</div>
      <div class="group-note">Faces saved by the camera (Alerts, then Faces) teach FaceWatch better than phone photos.</div>`
    : `<div class="empty">${icon("people")}<h2>No one yet</h2>
        <p>Add the people who live here so FaceWatch can tell them apart from strangers.</p>
        <a class="btn" href="#/people/new">Add Person</a></div>`;
}

function renderNewPerson() {
  setBar({ title: "New Person", back: ["#/people", "People"], sub: true });
  view.innerHTML = `
    <form id="new-person" style="margin-top:24px">
      <div class="group"><input class="field" name="name" maxlength="40" placeholder="Name"
        autocomplete="off" autocorrect="off" required></div>
      <div class="group-note">Letters, numbers and spaces. Next you'll take a few photos of their face.</div>
      <button class="btn">Continue</button>
    </form>`;
  $("#new-person").onsubmit = async event => {
    event.preventDefault();
    try {
      const r = await api("/people", { method: "POST", json: { name: event.target.elements.name.value.trim() } });
      freshPerson = r.name;
      go(`#/people/${enc(r.name)}`);
    } catch (e) { fail(e); }
  };
}

function cameraAppRow() {
  return `<label class="row">${tile("camera")}<span class="grow">Take Photo</span>${chevron()}
    <input type="file" accept="image/*" capture="user"></label>`;
}

async function renderPerson(name) {
  setBar({ title: name, back: ["#/people", "People"], sub: true });
  const isNew = freshPerson === name;
  freshPerson = null;
  view.innerHTML = `
    <div class="hero">
      <span id="hero-avatar">${avatar(name, null, "lg")}</span>
      <h1>${esc(name)}</h1>
      <p id="photo-count">&nbsp;</p>
    </div>
    ${isNew ? `<div class="group-note" style="margin:-10px 8px 18px;text-align:center">Take 3 to 5 photos: one facing the
      camera, then turned a little to each side. Add one with glasses if they wear them.</div>` : ""}
    <div class="group icons" id="photo-buttons">
      ${canUseCamera() ? `<button class="row" id="take">${tile("camera")}<span class="grow">Take Photo</span>${chevron()}</button>` : cameraAppRow()}
      <label class="row">${tile("image")}<span class="grow">Choose from Library</span>${chevron()}
        <input type="file" accept="image/*" multiple></label>
    </div>
    <div class="group hidden" id="results" style="margin-top:12px"></div>
    <div class="group-label">Photos</div>
    <div class="photos" id="photos"></div>
    <div class="group" style="margin-top:28px">
      <button class="row accent" id="rename">Rename</button>
      <button class="row danger" id="delete">Delete Person</button>
    </div>`;

  const grid = $("#photos");
  const results = $("#results");

  const load = async () => {
    const data = await api(`/people/${enc(name)}`);
    if (!grid.isConnected) return;
    $("#photo-count").textContent = data.photos.length ? plural(data.photos.length, "photo") : "No photos yet";
    $("#hero-avatar").innerHTML = avatar(name, data.photos[0], "lg");
    grid.innerHTML = data.photos.length
      ? data.photos.map(f => `
        <div class="photo">
          <img loading="lazy" alt="" src="/api/people/${enc(name)}/photos/${enc(f)}">
          <button data-file="${esc(f)}" aria-label="Delete photo">${icon("close")}</button>
        </div>`).join("")
      : `<div class="row muted" style="grid-column:1/-1;background:var(--group)">No photos yet</div>`;
  };

  const sendPhoto = async blob => {
    const form = new FormData();
    form.append("photo", blob, "photo.jpg");
    try {
      const r = await api(`/people/${enc(name)}/photos`, { method: "POST", form });
      return { kind: r.warning ? "warn" : "ok", text: r.warning || "Added" };
    } catch (e) {
      return { kind: "bad", text: e.message };
    }
  };

  const upload = async files => {
    results.innerHTML = "";
    results.classList.remove("hidden");
    for (const [i, file] of files.entries()) {
      const line = document.createElement("div");
      line.className = "row result";
      line.textContent = `Photo ${i + 1}: checking…`;
      results.append(line);
      const r = await sendPhoto(await shrinkImage(file));
      line.className = `row result ${r.kind}`;
      line.textContent = `Photo ${i + 1}: ${r.text}`;
    }
    load();
  };

  const watchInputs = () => {
    for (const input of view.querySelectorAll("#photo-buttons input[type=file]")) {
      input.onchange = () => {
        const files = [...input.files];
        input.value = "";
        if (files.length) upload(files);
      };
    }
  };
  watchInputs();

  let closeCamera = null;
  const take = $("#take");
  if (take) {
    take.onclick = () => {
      results.classList.add("hidden");
      closeCamera = openCamera(sendPhoto, reason => {
        closeCamera = null;
        load();
        if (reason === "done") return;
        // The in-app camera isn't allowed or available, so hand over to the phone's own camera app instead.
        take.outerHTML = cameraAppRow();
        watchInputs();
        toast(reason === "denied"
          ? "Camera access is blocked for this site. Allow it in your browser settings, or tap Take Photo to use your camera app."
          : "Couldn't open the camera here. Tap Take Photo to use your camera app.", "warn", 6000);
      });
    };
  }
  cleanup = () => { if (closeCamera) closeCamera(); };

  grid.onclick = async event => {
    const button = event.target.closest("button[data-file]");
    if (!button || !confirm("Delete this photo?")) return;
    try {
      await api(`/people/${enc(name)}/photos/${enc(button.dataset.file)}`, { method: "DELETE" });
      load();
    } catch (e) { fail(e); }
  };

  $("#rename").onclick = async () => {
    const newName = prompt("New name", name);
    if (!newName || newName.trim() === name) return;
    try {
      const r = await api(`/people/${enc(name)}`, { method: "PATCH", json: { name: newName.trim() } });
      go(`#/people/${enc(r.name)}`);
    } catch (e) { fail(e); }
  };

  $("#delete").onclick = async () => {
    if (!confirm(`Delete ${name} and all their photos? FaceWatch will stop recognising them.`)) return;
    try {
      await api(`/people/${enc(name)}`, { method: "DELETE" });
      toast(`${name} deleted`);
      go("#/people");
    } catch (e) { fail(e); }
  };

  await load();
}

function fileSize(bytes) {
  return bytes < 1e6 ? `${Math.max(1, Math.round(bytes / 1e3))} KB` : `${(bytes / 1e6).toFixed(bytes < 1e7 ? 1 : 0)} MB`;
}

async function renderAlerts() {
  setBar({ title: "Alerts", actions: '<button class="bar-btn" id="select-toggle">Select</button>' });
  view.innerHTML = `
    <h1 class="large-title">Alerts</h1>
    <div class="segmented">
      <button data-tab="history" class="on">History</button>
      <button data-tab="faces">Faces</button>
    </div>
    <div id="alerts-body"><div class="loading"><div class="spinner"></div></div></div>
    <div class="select-bar" id="select-bar">
      <button class="bar-btn" id="select-all">Select All</button>
      <span id="select-count">Tap to select</span>
      <button class="bar-btn danger" id="delete-picked" disabled>Delete</button>
    </div>`;
  const body = $("#alerts-body");
  let [alerts, summary] = await Promise.all([api("/alerts?limit=150"), api("/alerts/summary")]);
  if (!body.isConnected) return;
  let tab = "history";
  let unknownOnly = true;
  let selecting = false;
  const picked = new Set();
  let faces = [];
  const keyOf = (date, file) => `${date}/${file}`;

  const showHistory = () => {
    if (!alerts.length) {
      body.innerHTML = `<div class="empty">${icon("bell")}<h2>Nothing recorded yet</h2>
        <p>When the camera sees someone, a snapshot shows up here.</p></div>`;
      return;
    }
    const days = [];
    alerts.forEach((a, i) => {
      if (!days.length || days[days.length - 1].date !== a.date) days.push({ date: a.date, rows: [] });
      const on = picked.has(keyOf(a.date, a.file));
      days[days.length - 1].rows.push(`
        <button class="row alert-row ${on ? "picked" : ""}" data-i="${i}">
          ${selecting ? `<span class="pick ${on ? "on" : ""}"></span>` : ""}
          <img loading="lazy" alt="" src="/api/alerts/${a.date}/${enc(a.file)}?thumb=1">
          <div class="grow"><div class="title num">${clock(a.time)}${a.clip ? ' <span class="clip-tag">▶ Clip</span>' : ""}</div>
            <div class="names">${warningTag(a.warning)}${a.names.map(nameTag).join("")}</div></div>
          ${selecting ? "" : chevron()}
        </button>`);
    });
    body.innerHTML = days.map(d => `<div class="day">${dayLabel(d.date)}</div><div class="group">${d.rows.join("")}</div>`).join("")
      + (selecting ? "" : `
        <div class="group" style="margin-top:28px"><button class="row danger" data-act="delete-all">Delete All Alerts</button></div>
        <div class="group-note">${plural(summary.alerts, "alert")} with their snapshots and face pictures use ${fileSize(summary.bytes)} on the laptop.</div>`);
  };

  const showFaces = () => {
    faces = alerts.flatMap(a => a.faces.map(f => ({ ...f, date: a.date, time: a.time })))
      .filter(f => !unknownOnly || f.name === "Unknown");
    const count = unknownOnly ? summary.unknown_faces : summary.faces;
    body.innerHTML = `
      <div class="group" style="margin-top:16px">
        <label class="row"><span class="grow">Unknown faces only</span>
          <input type="checkbox" class="switch" id="unknown-only" ${unknownOnly ? "checked" : ""}></label>
      </div>
      <div class="group-note">${selecting ? "Tap faces to select them." : "Tap a face to add it to someone. Photos from the camera teach FaceWatch best."}</div>
      ${faces.length ? `<div class="faces">${faces.map((f, i) => `
        <button class="face ${picked.has(keyOf(f.date, f.file)) ? "picked" : ""}" data-face="${i}">
          <img loading="lazy" alt="" src="/api/alerts/${f.date}/faces/${enc(f.file)}">
          ${selecting ? `<span class="pick ${picked.has(keyOf(f.date, f.file)) ? "on" : ""}"></span>` : ""}
          <span class="${f.name === "Unknown" ? "unknown" : ""}">${esc(f.name)}</span>
        </button>`).join("")}</div>
        ${selecting ? "" : `<div class="group" style="margin-top:28px"><button class="row danger" data-act="delete-all">
          Delete All ${unknownOnly ? "Unknown " : ""}Faces</button></div>
        <div class="group-note">${plural(count, unknownOnly ? "unknown face" : "face")}. The snapshots in History stay.</div>`}`
        : `<div class="empty">${icon("scan")}<h2>No faces here</h2><p>Faces the camera saves will show up here.</p></div>`}`;
    $("#unknown-only").onchange = e => {
      unknownOnly = e.target.checked;
      picked.clear();
      show();
    };
  };

  // Select mode swaps the tab bar for a Select All / Delete bar, like a phone's photo gallery.
  const shownKeys = () => (tab === "history" ? alerts : faces).map(x => keyOf(x.date, x.file));
  const updateBar = () => {
    document.body.classList.toggle("selecting", selecting);
    $("#select-toggle").textContent = selecting ? "Done" : "Select";
    $("#select-count").textContent = picked.size ? `${picked.size} selected` : "Tap to select";
    $("#delete-picked").disabled = !picked.size;
    $("#select-all").textContent = picked.size && picked.size === shownKeys().length ? "Select None" : "Select All";
  };
  const show = () => {
    if (tab === "history") showHistory();
    else showFaces();
    updateBar();
  };
  // Ticks the picked items without redrawing the list, so the pictures don't flicker.
  const syncPicks = () => {
    body.querySelectorAll(".alert-row, [data-face]").forEach(el => {
      const item = el.dataset.i !== undefined ? alerts[+el.dataset.i] : faces[+el.dataset.face];
      const on = picked.has(keyOf(item.date, item.file));
      el.classList.toggle("picked", on);
      el.querySelector(".pick")?.classList.toggle("on", on);
    });
    updateBar();
  };
  const setSelecting = on => {
    selecting = on;
    picked.clear();
    show();
  };
  $("#select-toggle").onclick = () => setSelecting(!selecting);
  $("#select-all").onclick = () => {
    const keys = shownKeys();
    if (picked.size === keys.length) picked.clear();
    else keys.forEach(k => picked.add(k));
    syncPicks();
  };
  const refreshSummary = async () => {
    try { summary = await api("/alerts/summary"); } catch { /* the numbers just stay as they were */ }
  };
  $("#delete-picked").onclick = async () => {
    const what = plural(picked.size, tab === "history" ? "alert" : "face");
    if (!confirm(`Delete ${what}? This can't be undone.`)) return;
    const items = [...picked].map(k => ({ date: k.slice(0, 10), file: k.slice(11) }));
    try {
      const r = await api(tab === "history" ? "/alerts/delete" : "/alerts/faces/delete", { method: "POST", json: { items } });
      if (tab === "history") alerts = alerts.filter(a => !picked.has(keyOf(a.date, a.file)));
      else alerts = alerts.map(a => ({ ...a, faces: a.faces.filter(f => !picked.has(keyOf(a.date, f.file))) }));
      toast(`Deleted ${plural(r.deleted, tab === "history" ? "alert" : "face")}`);
      await refreshSummary();
      setSelecting(false);
    } catch (e) { fail(e); }
  };
  const deleteAll = async () => {
    await refreshSummary();
    const facesTab = tab === "faces";
    const count = facesTab ? (unknownOnly ? summary.unknown_faces : summary.faces) : summary.alerts;
    if (!count) return toast("There's nothing to delete.");
    const what = facesTab
      ? `all ${plural(count, unknownOnly ? "unknown face" : "face")}`
      : `all ${plural(count, "alert")}, with their snapshots and face pictures (${fileSize(summary.bytes)})`;
    if (!confirm(`Delete ${what}? This can't be undone.`)) return;
    try {
      const r = await api(facesTab ? "/alerts/faces/delete" : "/alerts/delete", {
        method: "POST", json: { all: true, unknown_only: unknownOnly },
      });
      if (facesTab) alerts = alerts.map(a => ({ ...a, faces: unknownOnly ? a.faces.filter(f => f.name !== "Unknown") : [] }));
      else alerts = [];
      toast(`Deleted ${plural(r.deleted, facesTab ? "face" : "alert")}`);
      await refreshSummary();
      show();
    } catch (e) { fail(e); }
  };

  const openAlert = a => {
    if (closeOverlay) closeOverlay();
    const box = document.createElement("div");
    box.className = "viewer";
    box.innerHTML = `
      <div class="viewer-top">
        <button class="bar-btn" data-act="close" aria-label="Close">${icon("close")}</button>
        <button class="bar-btn" data-act="delete" aria-label="Delete">${icon("trash")}</button>
      </div>
      ${a.clip
        // The snapshot (with the name boxes) shows until the clip is played.
        ? `<video controls playsinline preload="none" poster="/api/alerts/${a.date}/${enc(a.file)}" src="/api/alerts/${a.date}/${enc(a.clip)}"></video>`
        : `<img alt="Snapshot" src="/api/alerts/${a.date}/${enc(a.file)}">`}
      <div class="viewer-info">
        <div class="names">${warningTag(a.warning)}${a.names.map(nameTag).join("")}</div>
        <div class="when">${dayLabel(a.date)}, ${clock(a.time)}</div>
      </div>`;
    const close = () => {
      box.remove();
      if (closeOverlay === close) closeOverlay = null;
    };
    box.onclick = async event => {
      const act = event.target.closest("[data-act]")?.dataset.act;
      if (act === "close") close();
      if (act === "delete" && confirm("Delete this snapshot?")) {
        try {
          await api(`/alerts/${a.date}/${enc(a.file)}`, { method: "DELETE" });
          alerts = alerts.filter(x => x !== a);
          close();
          await refreshSummary();
          show();
        } catch (e) { fail(e); }
      }
    };
    document.body.append(box);
    closeOverlay = close;
  };

  const assignFace = async face => {
    let people = [];
    try { people = await api("/people"); } catch (e) { return fail(e); }
    const { sheet, close } = openSheet(`
      <img class="face-preview" alt="" src="/api/alerts/${face.date}/faces/${enc(face.file)}">
      <h2>Who is this?</h2>
      ${people.length ? `<div class="group avatars">${people.map(p => `
        <button class="row" data-name="${esc(p.name)}">${avatar(p.name, p.cover)}<span class="grow">${esc(p.name)}</span></button>`).join("")}</div>
        <div class="group-label">Someone new</div>` : ""}
      <form>
        <div class="group"><input class="field" name="name" maxlength="40" placeholder="Name" autocomplete="off" autocorrect="off"></div>
        <button class="btn">Add</button>
        <button type="button" class="btn secondary" data-act="cancel" style="margin-top:10px">Cancel</button>
      </form>`);
    const save = async personName => {
      if (!personName) return toast("Pick someone or type a name.", "error");
      try {
        const r = await api(`/alerts/${face.date}/faces/${enc(face.file)}/assign`, { method: "POST", json: { name: personName } });
        close();
        toast(r.warning || `Added to ${r.name}`, r.warning ? "warn" : "");
      } catch (e) { fail(e); }
    };
    sheet.addEventListener("click", event => {
      const pick = event.target.closest("[data-name]");
      if (pick) save(pick.dataset.name);
    });
    $("form", sheet).onsubmit = event => {
      event.preventDefault();
      save(event.target.elements.name.value.trim());
    };
  };

  view.querySelectorAll(".segmented button").forEach(button => {
    button.onclick = () => {
      tab = button.dataset.tab;
      view.querySelectorAll(".segmented button").forEach(b => b.classList.toggle("on", b === button));
      picked.clear();
      show();
    };
  });
  body.onclick = event => {
    if (event.target.closest('[data-act="delete-all"]')) return deleteAll();
    const row = event.target.closest(".alert-row");
    const face = event.target.closest("[data-face]");
    const item = row ? alerts[+row.dataset.i] : face ? faces[+face.dataset.face] : null;
    if (!item) return;
    if (!selecting) return row ? openAlert(item) : assignFace(item);
    const key = keyOf(item.date, item.file);
    if (picked.has(key)) picked.delete(key);
    else picked.add(key);
    syncPicks();
  };
  cleanup = () => document.body.classList.remove("selecting");
  show();
}

async function renderSettings() {
  setBar({ title: "Settings" });
  const [s, accounts, status, zones, stored] = await Promise.all([
    api("/settings"), api("/accounts"), api("/status"), api("/zones"), api("/alerts/summary"),
  ]);
  if (location.hash !== "#/settings") return;
  const toggle = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input type="checkbox" class="switch" name="${key}" ${s[key] ? "checked" : ""}></label>`;
  const seconds = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input class="inline short num" type="number" inputmode="numeric" name="${key}" value="${s[key]}"><span class="unit">s</span></label>`;
  const minutes = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input class="inline short num" type="number" inputmode="numeric" name="${key}" value="${s[key]}"><span class="unit">min</span></label>`;
  const hour = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input class="inline short num" type="number" inputmode="numeric" name="${key}" value="${s[key]}"><span class="unit">:00</span></label>`;
  const days = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input class="inline short num" type="number" inputmode="numeric" name="${key}" value="${s[key]}"><span class="unit">days</span></label>`;
  const volume = (key, label) => `
    <div class="row" style="display:block">
      <div style="display:flex;justify-content:space-between"><span>${label}</span><span class="value num" data-shows="${key}">${s[key]}%</span></div>
      <input type="range" name="${key}" min="0" max="100" step="5" value="${s[key]}">
    </div>`;
  const times = (key, label) => `
    <label class="row"><span class="grow">${label}</span>
      <input class="inline short num" type="number" inputmode="numeric" name="${key}" value="${s[key]}"><span class="unit">times</span></label>`;
  view.innerHTML = `
    <h1 class="large-title">Settings</h1>
    <form id="settings" onsubmit="return false">
      <div class="group-label">Camera</div>
      <div class="group">
        <label class="row"><span>Name</span><input class="inline" name="camera_name" maxlength="40" value="${esc(s.camera_name)}"></label>
        ${toggle("camera_autostart", "Turn on when FaceWatch starts")}
      </div>
      <div class="group-note">Keeps alerts working after the laptop restarts, without anyone opening Live.</div>
      <div class="group" style="margin-top:14px">${toggle("own_camera_link", "Steady video link")}</div>
      <div class="group-note">FaceWatch keeps the connection to the camera itself, so the video doesn't stop for a second
        every 12 s as go2rtc's own connection does. Turn it off to use go2rtc's (needed for Talk and the alarm). The
        camera restarts to switch.</div>
      <div class="group" style="margin-top:14px">
        <label class="row"><span class="grow">Follow movement</span>
          <input type="checkbox" class="switch" id="tracking" disabled></label>
      </div>
      <div class="group-note" id="tracking-note">Asking the camera…</div>
      <div class="group" style="margin-top:14px">
        ${toggle("camera_control", "Camera arrows")}
        ${toggle("follow_faces", "Follow faces")}
        ${toggle("follow_known", "Also follow people I know")}
        ${minutes("origin_return_minutes", "Back to origin after")}
      </div>
      <div class="group-note">Camera arrows: the arrows on the Live video and Origin. Off hides them, and nothing turns the
        camera from here. Follow faces turns it towards unknown people (and people you know, if chosen) and back to the
        origin 10 s after they've gone. Back to origin: after nobody has used the arrows for this long; 0 = never.</div>

      <div class="group-label">Telegram messages</div>
      <div class="group">
        ${toggle("notify_unknown", "Unknown people")}
        ${toggle("notify_hidden", "Someone hiding their face")}
        ${toggle("notify_known", "People I know arriving")}
        ${toggle("notify_offline", "Camera goes offline")}
      </div>
      <div class="group-note">Everyone the camera sees is saved in Alerts. These only choose what also sends you a message.</div>
      <div class="group" style="margin-top:14px">
        ${toggle("home_mode", "Home mode (pause people alerts)")}
        ${toggle("daily_summary", "Daily summary")}
        ${hour("summary_hour", "Summary at")}
      </div>
      <div class="group-note">Home mode stops alerts about people reaching Telegram while you're home; they're still saved in
        Alerts. The bot also takes commands: /home and /away switch it, /photo sends a picture now, /status and /summary
        say what's going on. The summary is one message a day with what the camera saw.</div>

      <div class="group-label">Unknown people</div>
      <div class="group">
        ${seconds("unknown_alert_after_seconds", "Alert after")}
        ${seconds("unknown_grace_seconds", "Allowed gap")}
        ${seconds("unknown_cooldown_seconds", "Repeat at most every")}
      </div>
      <div class="group-note">Someone has to stay in view this long before an alert. A short gap, like turning away, doesn't restart the count.</div>

      <div class="group-label">Zones</div>
      <div class="group icons">
        <a class="row" href="#/zones">${tile("zones")}<span class="grow">Zone lines</span>
          <span class="value">${zones.lines ? "Drawn" : "Not drawn"}</span>${chevron()}</a>
      </div>
      <div class="group" style="margin-top:10px">
        ${toggle("notify_zones", "Zone warnings")}
        ${seconds("zone_alert_after_seconds", "Warn after")}
        ${times("entrance_messages", "Past line 1 (Entrance)")}
        ${times("inside_messages", "Past line 2 (Inside)")}
        ${seconds("zone_cooldown_seconds", "Repeat at most every")}
      </div>
      <div class="group-note">An unknown person outside the first line gets the normal alert, marked "outside". Past a line, you get a warning instead, sent several times a few seconds apart so your phone keeps buzzing.</div>

      <div class="group-label">Camera speaker</div>
      <div class="group">${toggle("camera_speaker", "Talk and Alarm")}</div>
      <div class="group-note">Keep this off for now. go2rtc 1.9.14 has a bug (issue #2175) that turns every sound sent to
        Xiaomi cameras into loud static. Turn it on only after updating go2rtc to a version with the fix.</div>
      <div id="speaker-options" class="${s.camera_speaker ? "" : "hidden"}">
        <div class="group" style="margin-top:10px">
          ${volume("talk_volume", "Talk volume")}
          ${volume("alarm_volume", "Alarm volume")}
          ${toggle("alarm_inside", "Alarm when someone unknown gets inside")}
          <button type="button" class="row accent" id="test-alarm">Test the Alarm</button>
        </div>
        <div class="group-note">The alarm is a siren and "You are being recorded" from the camera's own speaker, when an unknown
          person passes line 2. While it plays, Test turns into Stop, and Live shows a Stop button too.</div>
      </div>

      <div class="group-label">Clips</div>
      <div class="group">${seconds("clip_seconds", "Video clip length")}</div>
      <div class="group-note">Added to alerts about unknown or hidden people, half before and half after, in History and on
        Telegram. 0 turns clips off.</div>

      <div class="group-label">Face hidden</div>
      <div class="group">
        ${seconds("hidden_alert_after_seconds", "Alert after")}
        ${seconds("hidden_cooldown_seconds", "Repeat at most every")}
      </div>
      <div class="group-note">${status.person_detection === false && status.detector
        ? "Needs YOLO, which isn't running, so this alert is off for now."
        : "For someone in a mask or cap, or with their back turned. Not sent if someone you know was recognised in the last minute, since it's most likely them."}</div>

      <div class="group-label">Camera offline</div>
      <div class="group">${seconds("offline_alert_after_seconds", "Alert after")}</div>
      <div class="group-note">You'll also get a message when it's back, and after the laptop has been asleep. Nothing can be sent while the laptop itself is asleep or off.</div>

      <div class="group-label">People I know</div>
      <div class="group">${seconds("cooldown_seconds", "Save again at most every")}</div>

      <div class="group-label">Storage</div>
      <div class="group">${days("keep_alert_days", "Keep alerts for")}</div>
      <div class="group-note">Older alerts, with their snapshots and face pictures, are deleted by themselves. 0 keeps them
        forever. Alerts use ${fileSize(stored.bytes)} on the laptop now.</div>

      <div class="group-label">Recognition</div>
      <div class="group">
        <div class="row" style="display:block">
          <div style="display:flex;justify-content:space-between"><span>Match strictness</span>
            <span class="value num" id="threshold-value">${s.match_threshold.toFixed(2)}</span></div>
          <input type="range" name="match_threshold" min="0.30" max="0.60" step="0.01" value="${s.match_threshold}">
        </div>
        <div class="row"><span class="grow">Face detection</span><span class="value">${esc(status.detector || "Starts with the camera")}</span></div>
      </div>
      <div class="group-note">Lower the strictness if family members show up as Unknown. Raise it if strangers get someone's name.
        ${status.detector_note ? `<br><br>${esc(status.detector_note)}` : ""}</div>
    </form>

    <div class="group-label">Logins</div>
    <div class="group avatars" id="accounts">
      ${accounts.map(a => `
        <div class="row"><span class="avatar">${esc(a.username[0].toUpperCase())}</span>
          <div class="grow"><div class="title">${esc(a.username)}${a.username === me ? ' <span class="dim">(you)</span>' : ""}</div>
            <div class="detail">Added ${new Date(a.created).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</div></div>
          ${a.username === me ? "" : `<button class="bar-btn" style="color:var(--red)" data-user="${esc(a.username)}">Remove</button>`}
        </div>`).join("")}
      <button class="row accent" id="add-login"><span class="avatar" style="background:none;color:var(--accent)">${icon("plus")}</span>Add Login</button>
    </div>

    <div class="group icons" style="margin-top:20px">
      <button class="row" id="change-password">${tile("key")}<span class="grow">Change Password</span>${chevron()}</button>
      <button class="row" id="install">${tile("phone")}<span class="grow">Add to Home Screen</span>${chevron()}</button>
    </div>

    <div class="group" style="margin-top:20px"><button class="row danger" id="logout">Sign Out</button></div>
    <div class="group-note" style="text-align:center;margin-top:12px">Signed in as ${esc(me)}</div>`;

  const form = $("#settings");
  form.elements.match_threshold.oninput = e => { $("#threshold-value").textContent = Number(e.target.value).toFixed(2); };
  form.addEventListener("input", e => {
    const shows = form.querySelector(`[data-shows="${e.target.name}"]`);
    if (shows) shows.textContent = `${e.target.value}%`;
  });

  const testAlarm = $("#test-alarm");
  let alarmTimer = null;
  const showAlarm = playing => {
    clearTimeout(alarmTimer);
    testAlarm.textContent = playing ? "Stop the Alarm" : "Test the Alarm";
    testAlarm.classList.toggle("danger", playing);
    testAlarm.classList.toggle("accent", !playing);
  };
  testAlarm.onclick = async () => {
    try {
      if (testAlarm.classList.contains("danger")) {
        await api("/sound/stop", { method: "POST" });
        return showAlarm(false);
      }
      if (!confirm(`Play the alarm on the camera now, at ${s.alarm_volume}% volume? You can stop it straight away.`)) return;
      const { seconds } = await api("/alarm/test", { method: "POST" });
      showAlarm(true);
      alarmTimer = setTimeout(() => showAlarm(false), seconds * 1000);
    } catch (e) { fail(e); }
  };
  if (status.alarm) showAlarm(true);

  // Motion tracking is the camera's own setting (through Xiaomi's cloud).
  const tracking = $("#tracking");
  const trackingNote = "The camera turns by itself to follow people. Zone lines follow it for turns of up to about 30°; "
    + "further than that, zone warnings pause until it turns back.";
  api("/camera/tracking").then(t => {
    tracking.disabled = !t.available;
    tracking.checked = !!t.on;
    $("#tracking-note").textContent = t.available ? trackingNote : t.error;
  }).catch(e => { $("#tracking-note").textContent = e.message; });
  tracking.onchange = async () => {
    tracking.disabled = true;
    try {
      const t = await api("/camera/tracking", { method: "PUT", json: { on: tracking.checked } });
      tracking.checked = t.on;
      if (t.on && s.follow_faces) {
        Object.assign(s, await api("/settings", { method: "PUT", json: { follow_faces: false } }));
        form.elements.follow_faces.checked = false;
      }
      toast(t.on ? "The camera will follow movement" : "Motion tracking off", "", 1800);
    } catch (e) {
      tracking.checked = !tracking.checked;
      fail(e);
    }
    tracking.disabled = false;
  };
  form.addEventListener("change", async event => {
    const input = event.target;
    const key = input.name;
    if (!key) return;
    const value = input.type === "checkbox" ? input.checked
      : input.type === "number" || input.type === "range" ? Number(input.value) : input.value.trim();
    if (key === "camera_speaker" && value && !confirm("Only turn this on after updating go2rtc to a version that fixes "
      + "issue #2175. With go2rtc 1.9.14 the camera plays loud static instead of sound. Turn it on?")) {
      input.checked = false;
      return;
    }
    try {
      Object.assign(s, await api("/settings", { method: "PUT", json: { [key]: value } }));
      $("#speaker-options").classList.toggle("hidden", !s.camera_speaker);
      if (key === "follow_faces" && value && tracking.checked) {
        await api("/camera/tracking", { method: "PUT", json: { on: false } });
        tracking.checked = false;
        return toast("Saved. Follow movement is off now, so the two don't fight.", "", 2600);
      }
      toast("Saved", "", 1400);
    } catch (e) {
      fail(e);
      if (input.type === "checkbox") input.checked = s[key];
      else input.value = s[key];
      if (key === "match_threshold") $("#threshold-value").textContent = s[key].toFixed(2);
    }
  });

  $("#accounts").onclick = async event => {
    const user = event.target.closest("[data-user]")?.dataset.user;
    if (!user || !confirm(`Remove the login "${user}"? They'll be signed out straight away.`)) return;
    try {
      await api(`/accounts/${enc(user)}`, { method: "DELETE" });
      renderSettings();
    } catch (e) { fail(e); }
  };

  $("#add-login").onclick = () => {
    const { sheet, close } = openSheet(`
      <h2>Add Login</h2>
      <form>
        <div class="group">
          <input class="field" name="username" placeholder="Username" autocomplete="off" autocapitalize="none" autocorrect="off" required>
          <input class="field" name="password" type="password" placeholder="Password, 8 or more characters" autocomplete="new-password" required>
        </div>
        <div class="group-note">For someone else in the household. They can change the password later.</div>
        <button class="btn">Add</button>
        <button type="button" class="btn secondary" data-act="cancel" style="margin-top:10px">Cancel</button>
      </form>`);
    $("form", sheet).onsubmit = async event => {
      event.preventDefault();
      const f = event.target.elements;
      try {
        await api("/accounts", { method: "POST", json: { username: f.username.value.trim(), password: f.password.value } });
        close();
        toast(`Added ${f.username.value.trim()}`);
        renderSettings();
      } catch (e) { fail(e); }
    };
  };

  $("#change-password").onclick = () => {
    const { sheet, close } = openSheet(`
      <h2>Change Password</h2>
      <form>
        <div class="group">
          <input class="field" name="current" type="password" placeholder="Current password" autocomplete="current-password" required>
          <input class="field" name="next" type="password" placeholder="New password, 8 or more characters" autocomplete="new-password" required>
        </div>
        <button class="btn">Change Password</button>
        <button type="button" class="btn secondary" data-act="cancel" style="margin-top:10px">Cancel</button>
      </form>`);
    $("form", sheet).onsubmit = async event => {
      event.preventDefault();
      const f = event.target.elements;
      try {
        await api("/password", { method: "POST", json: { current_password: f.current.value, new_password: f.next.value } });
        close();
        toast("Password changed");
      } catch (e) { fail(e); }
    };
  };

  $("#install").onclick = () => openSheet(`
    <h2>Add to Home Screen</h2>
    <div class="group">
      <div class="row" style="display:block"><div class="title">iPhone</div>
        <div class="detail">Open this page in Safari, tap Share, then Add to Home Screen.</div></div>
      <div class="row" style="display:block"><div class="title">Android</div>
        <div class="detail">Open this page in Chrome, tap the ⋮ menu, then Install app.</div></div>
    </div>
    <div class="group-note">Use the https address from Tailscale, so it installs as a proper app and can use the camera.</div>
    <button class="btn secondary" data-act="cancel">Done</button>`);

  $("#logout").onclick = async () => {
    try { await api("/logout", { method: "POST" }); } catch {}
    me = null;
    showLogin(false);
  };
}

async function start() {
  document.querySelectorAll(".tabs a").forEach(a => { a.innerHTML = `${icon(a.dataset.icon)}<span>${a.textContent}</span>`; });
  window.addEventListener("scroll", onScroll, { passive: true });
  try {
    const s = await api("/session");
    if (!s.user) return showLogin(s.needs_setup);
    me = s.user;
    document.body.classList.remove("auth");
    route();
  } catch (e) {
    view.innerHTML = `<div class="empty"><h2>Can't connect</h2><p>${esc(e.message)}</p>
      <button class="btn secondary" onclick="location.reload()">Try Again</button></div>`;
  }
}

window.addEventListener("hashchange", route);
// Service workers only run on https:// (e.g. the Tailscale address); plain http still works without one.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
start();
