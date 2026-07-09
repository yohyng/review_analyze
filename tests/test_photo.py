"""Tests for facility photo storage (resize + BLOB round-trip)."""
import base64
import io

import pytest

from src import db, images
from src.db import _encode_params, _parse_turso_result


def _png(w=2000, h=1400):
    from PIL import Image
    im = Image.new("RGB", (w, h), (180, 60, 140))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_resize_shrinks_and_jpegs():
    from PIL import Image
    raw = _png(2000, 1400)
    out, mime = images.resize_for_storage(raw, max_px=1200)
    assert mime == "image/jpeg"
    im = Image.open(io.BytesIO(out))
    assert max(im.size) == 1200
    assert len(out) <= len(raw)


def test_resize_keeps_small_images_within_bounds():
    from PIL import Image
    raw = _png(400, 300)
    out, mime = images.resize_for_storage(raw, max_px=1200)
    im = Image.open(io.BytesIO(out))
    assert max(im.size) == 400  # not upscaled


def test_resize_empty_bytes():
    out, mime = images.resize_for_storage(b"")
    assert out == b""


def test_photo_roundtrip_sqlite():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "T", category="企業ミュージアム")
    blob, mime = images.resize_for_storage(_png())
    assert db.get_photo(conn, fid) is None
    db.save_photo(conn, fid, blob, mime)
    got = db.get_photo(conn, fid)
    assert got is not None
    assert got["image"] == blob
    assert got["mime"] == mime
    assert got["updated_at"]
    assert db.photo_updated_at(conn, fid) is not None


def test_photo_overwrite_and_delete():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "T")
    db.save_photo(conn, fid, b"\x01\x02\x03", "image/jpeg")
    db.save_photo(conn, fid, b"\x09\x08", "image/png")   # overwrite
    got = db.get_photo(conn, fid)
    assert got["image"] == b"\x09\x08" and got["mime"] == "image/png"
    # single row per facility
    n = conn.execute("SELECT COUNT(*) FROM facility_photo WHERE facility_id = ?", (fid,)).fetchone()[0]
    assert n == 1
    db.delete_photo(conn, fid)
    assert db.get_photo(conn, fid) is None


def test_turso_blob_encode_decode():
    # bytes → Turso arg object → back to bytes
    raw = _png(300, 200)
    arg = [a for a in _encode_params((1, raw, "image/jpeg")) if a.get("type") == "blob"][0]
    assert arg["type"] == "blob"
    assert base64.b64decode(arg["base64"]) == raw

    # a Turso SELECT result with a blob cell decodes back to bytes
    fake = {"response": {"result": {
        "cols": [{"name": "image"}],
        "rows": [[{"type": "blob", "base64": base64.b64encode(raw).decode()}]],
    }}}
    cur = _parse_turso_result(fake)
    assert cur.fetchall()[0][0] == raw
