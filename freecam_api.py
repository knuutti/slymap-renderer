import json
import urllib.error
import urllib.parse
import urllib.request

# SluMAN camera script API (Practice Mode > Camera tab > Script API)
BASE_URL = "http://127.0.0.1:9675"


class ApiError(RuntimeError):
    pass


class GameRefused(ApiError):
    """409: the game refused, e.g. a level is still loading. Worth retrying."""
    pass


def get(path, **params):
    url = BASE_URL + path
    params = {k: v for k, v in params.items() if v is not None}
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            message = json.load(e).get("error", str(e))
        except ValueError:
            message = str(e)
        if e.code == 409:
            raise GameRefused(message)
        raise ApiError(f"{e.code}: {message}")
    except urllib.error.URLError as e:
        raise ApiError(f"Can't reach the camera API at {BASE_URL} ({e.reason}). "
                       "Is SluMAN in Practice Mode with Script API ticked?")


def info():
    return get("/")


def up_axis():
    return info()["upAxis"]


def supports_far():
    return any("far=" in r for r in info()["requests"])


def get_camera():
    return get("/camera")


def set_camera(x, y, z, yaw, pitch, fov, far=None):
    return get("/camera/set", x=x, y=y, z=z, yaw=yaw, pitch=pitch, fov=fov, far=far)


def camera_off():
    return get("/camera/off")


def set_hud(hidden):
    return get("/hud", hidden=int(hidden))


def set_fog(off):
    return get("/fog", off=int(off))
