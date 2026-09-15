"""Google マップの場所URLを読む。

KAIZODE は収集対象を URL で受け取る。その際に**確実なのは、マップで施設を
開いたときにアドレスバーに出るこの形**:

    https://www.google.com/maps/place/<名前>/@<lat>,<lng>,<zoom>/
      data=!3m2!1e3!5s<...>!4m6!3m5!1s<0x…:0x…>!8m2!3d<lat>!4d<lng>!16s<mid>?…

`/maps/search/?query=名前` や `/maps/place/?q=place_id:…` でも施設には飛べるが、
KAIZODE 側ではこの「場所URL」を正とする、とのこと。
そのため:

  - 人が URL を貼ったら、**そのまま**KAIZODE に渡す（作り直さない）
  - 施設名から始めたときは Places API の googleMapsUri を使う
    （Google 自身が返す、その施設の正規URL）

ここが読むのは表示と照合のための材料だけ。lat/lng は `!8m2!3d…!4d…` を優先する
（`@…` は地図の中心で、施設の座標とは限らない。実例では経度が 0.003 ずれる）。
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

_PLACE_RE = re.compile(r"/maps/place/([^/@?]+)")
_AT_RE = re.compile(r"/@(-?\d+\.?\d*),(-?\d+\.?\d*)")
_COORD_RE = re.compile(r"!8m2!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)")
_FID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)")
_MID_RE = re.compile(r"!16s([^!?&]+)")
_PLACE_ID_RE = re.compile(r"place_id:([A-Za-z0-9_-]+)")

_HOSTS = ("google.com", "google.co.jp", "goo.gl", "maps.app.goo.gl")


@dataclass
class MapsLink:
    url: str                    # 貼られたそのまま。KAIZODE にはこれを渡す
    name: str = ""
    lat: float | None = None
    lng: float | None = None
    fid: str = ""               # 0x…:0x… （place_id とは別物）
    mid: str = ""               # /g/… 形式の ID
    place_id: str = ""          # ?q=place_id:… の形で貼られた場合だけ
    short: bool = False         # maps.app.goo.gl の短縮URL

    @property
    def precise(self) -> bool:
        """その施設1件を指していると言えるか。

        fid / mid / place_id のどれかがあれば1件に定まる。名前と座標だけの
        URL は、地図を動かしただけのものかもしれないので信用しない。
        """
        return bool(self.fid or self.mid or self.place_id)


def looks_like_url(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("http://") or s.startswith("https://")


def is_maps_url(s: str) -> bool:
    if not looks_like_url(s):
        return False
    try:
        host = urllib.parse.urlparse(s.strip()).netloc.lower()
    except Exception:
        return False
    host = host.split(":")[0]
    return any(host == h or host.endswith("." + h) for h in _HOSTS)


def parse(url: str) -> "MapsLink | None":
    """場所URLから、照合に使える手がかりを取り出す。マップのURLでなければ None。"""
    u = (url or "").strip()
    if not is_maps_url(u):
        return None

    link = MapsLink(url=u)
    host = urllib.parse.urlparse(u).netloc.lower()
    if "goo.gl" in host:
        # 短縮URL。中身は開かないと分からない（ここでは通信しない）。
        link.short = True
        return link

    m = _PLACE_RE.search(u)
    if m:
        raw = m.group(1)
        if not raw.startswith("?"):
            link.name = urllib.parse.unquote_plus(raw).replace("+", " ").strip()

    # 座標は !8m2!3d…!4d… を優先（@… は地図の中心）
    m = _COORD_RE.search(u)
    if m:
        link.lat, link.lng = float(m.group(1)), float(m.group(2))
    else:
        m = _AT_RE.search(u)
        if m:
            link.lat, link.lng = float(m.group(1)), float(m.group(2))

    m = _FID_RE.search(u)
    if m:
        link.fid = m.group(1)
    m = _MID_RE.search(u)
    if m:
        link.mid = urllib.parse.unquote(m.group(1))
    m = _PLACE_ID_RE.search(u)
    if m:
        link.place_id = m.group(1)
    return link
