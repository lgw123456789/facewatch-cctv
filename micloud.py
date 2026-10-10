"""Camera settings, and the keys for FaceWatch's own camera link, through Xiaomi's cloud as the Mi Home app does, with
the login go2rtc saved in go2rtc.yaml."""
import base64
import hashlib
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

import requests
import yaml

# (service id, property id) per camera model, from Xiaomi's specs (miot-spec.org).
PROPERTIES = {"mxiang.camera.c301": {"motion tracking": (2, 8), "speaker volume": (6, 1)}}


class MiCloudError(Exception):
    pass


def rc4(key, data):
    """RC4 with the first 1024 bytes of keystream dropped, as Xiaomi's API uses."""
    s, j = list(range(256)), 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for n in range(1024 + len(data)):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        if n >= 1024:
            out.append(data[n - 1024] ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def signature(path, form, signed_nonce):
    text = f"POST&{path}&data={form['data']}"
    if "rc4_hash__" in form:
        text += f"&rc4_hash__={form['rc4_hash__']}"
    text += "&" + base64.b64encode(signed_nonce).decode()
    return base64.b64encode(hashlib.sha1(text.encode()).digest()).decode()


class MiCloud:
    def __init__(self, go2rtc_yaml, stream="xiaomi_cam"):
        self.go2rtc_yaml, self.stream = go2rtc_yaml, stream
        self.lock = threading.Lock()
        self.session = None  # (cookies, ssecurity, logged-in time)

    def camera(self):
        """(user id, pass token, region, device id, model, camera address) from go2rtc.yaml."""
        try:
            cfg = yaml.safe_load(self.go2rtc_yaml.read_text(encoding="utf-8")) or {}
            link = urlparse(cfg["streams"][self.stream])
            user_id, region = link.username, link.password
            query = parse_qs(link.query)
            token = (cfg.get("xiaomi") or {}).get(user_id) or (cfg.get("xiaomi") or {}).get(int(user_id))
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
            raise MiCloudError("go2rtc.yaml has no Xiaomi camera set up.")
        if link.scheme != "xiaomi" or not token:
            raise MiCloudError("The camera isn't connected through a Xiaomi login in go2rtc.yaml.")
        return user_id, token, region, query["did"][0], query.get("model", [""])[0], link.hostname

    def _login(self, user_id, token):
        s = requests.Session()
        r = s.get("https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=xiaomiio",
                  headers={"Cookie": f"userId={user_id}; passToken={token}"}, timeout=15)
        login = json.loads(r.text.removeprefix("&&&START&&&"))
        if not login.get("ssecurity") or not login.get("location"):
            raise MiCloudError("Xiaomi refused the saved login. Log in to Xiaomi again in go2rtc's page.")
        r = s.get(login["location"], timeout=15)
        jar = {c.name: c.value for resp in [*r.history, r] for c in resp.cookies}
        jar.update({c.name: c.value for c in s.cookies})
        if "serviceToken" not in jar:
            raise MiCloudError("Xiaomi didn't finish the login. Try again in a minute.")
        cookies = f"userId={jar.get('userId', user_id)}; cUserId={jar.get('cUserId', '')}; serviceToken={jar['serviceToken']}"
        return cookies, base64.b64decode(login["ssecurity"]), time.time()

    def _post(self, region, path, params):
        cookies, ssecurity, _ = self.session
        nonce = os.urandom(8) + int(time.time() // 60).to_bytes(4, "big")
        signed = hashlib.sha256(ssecurity + nonce).digest()
        form = {"data": json.dumps(params)}
        form["rc4_hash__"] = signature(path, form, signed)
        form = {k: base64.b64encode(rc4(signed, v.encode())).decode() for k, v in form.items()}
        form["signature"] = signature(path, form, signed)
        form["_nonce"] = base64.b64encode(nonce).decode()
        base = f"https://{region}.api.io.mi.com/app" if region in ("de", "i2", "ru", "sg", "us") else "https://api.io.mi.com/app"
        r = requests.post(base + path, data=form, headers={"Cookie": cookies}, timeout=15)
        r.raise_for_status()
        return json.loads(rc4(signed, base64.b64decode(r.text)))

    def _call(self, path, params):
        user_id, token, region = self.camera()[:3]
        with self.lock:
            for attempt in (1, 2):
                try:
                    # Sessions last about a day: log in again well before that, or after a failure.
                    if self.session is None or time.time() - self.session[2] > 6 * 3600:
                        self.session = self._login(user_id, token)
                    reply = self._post(region, path, params)
                except (requests.RequestException, ValueError) as e:
                    self.session = None
                    if attempt == 2:
                        raise MiCloudError(f"Couldn't reach Xiaomi ({type(e).__name__}). Check the internet.")
                    continue
                if reply.get("code") != 0:
                    raise MiCloudError(f"Xiaomi said: {reply.get('message') or reply.get('code')}")
                return reply.get("result")

    def _property(self, name):
        did, model = self.camera()[3:5]
        if name not in PROPERTIES.get(model, {}):
            raise MiCloudError(f"Changing the {name} isn't supported for this camera model ({model or 'unknown'}) yet.")
        siid, piid = PROPERTIES[model][name]
        return {"did": did, "siid": siid, "piid": piid}

    def get(self, name):
        item = (self._call("/miotspec/prop/get", {"params": [self._property(name)]}) or [{}])[0]
        if item.get("code") != 0:
            raise MiCloudError("The camera didn't answer. Is it switched on and online?")
        return item["value"]

    def set(self, name, value):
        item = (self._call("/miotspec/prop/set", {"params": [{**self._property(name), "value": value}]}) or [{}])[0]
        if item.get("code") not in (0, 1):  # 1: accepted, still being applied
            raise MiCloudError("The camera didn't accept the change. Is it switched on and online?")
        return value

    def motion_tracking(self):
        return bool(self.get("motion tracking"))

    def set_motion_tracking(self, on):
        return bool(self.set("motion tracking", bool(on)))

    def set_volume(self, percent):
        return self.set("speaker volume", int(percent))

    def miss_vendor(self, app_public_key):
        """The camera's public key and a signed pass for FaceWatch's own link (ptz.py)."""
        did = self.camera()[3]
        return self._call("/v2/device/miss_get_vendor",
                          {"app_pubkey": app_public_key, "did": did, "support_vendors": "TUTK_CS2_MTP"}) or {}
