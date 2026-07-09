"""施設写真の自動リサイズ（保存前に軽量化）。

Turso の1リクエストサイズ上限を超えないよう、長辺を縮小し JPEG で再エンコード。
Pillow が無い環境では原画をそのまま返す（呼び出し側でサイズに注意）。
"""
from __future__ import annotations

import io


def resize_for_storage(image_bytes: bytes, max_px: int = 1200, quality: int = 80):
    """(縮小後 bytes, mime) を返す。失敗時は原画を返す。"""
    if not image_bytes:
        return image_bytes, "image/jpeg"
    try:
        from PIL import Image
    except Exception:
        return image_bytes, "image/jpeg"
    try:
        im = Image.open(io.BytesIO(image_bytes))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_px / max(w, h)) if max(w, h) else 1.0
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"
