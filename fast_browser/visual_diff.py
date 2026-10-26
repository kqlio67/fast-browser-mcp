import base64
import hashlib
import os
import struct
import zlib
from typing import Any

# Optional Pillow acceleration if installed
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    return c


def _unfilter_scanlines(
    raw: bytes, width: int, height: int, bpp: int
) -> bytearray:
    row_bytes = width * bpp
    out = bytearray(height * row_bytes)
    stride = row_bytes + 1
    for y in range(height):
        filter_type = raw[y * stride]
        r_start = y * stride + 1
        row = raw[r_start : r_start + row_bytes]
        out_start = y * row_bytes
        prev_start = (y - 1) * row_bytes if y > 0 else None

        if filter_type == 0:  # None
            out[out_start : out_start + row_bytes] = row
        elif filter_type == 1:  # Sub
            for x in range(row_bytes):
                left = out[out_start + x - bpp] if x >= bpp else 0
                out[out_start + x] = (row[x] + left) & 0xFF
        elif filter_type == 2:  # Up
            if prev_start is not None:
                for x in range(row_bytes):
                    above = out[prev_start + x]
                    out[out_start + x] = (row[x] + above) & 0xFF
            else:
                out[out_start : out_start + row_bytes] = row
        elif filter_type == 3:  # Average
            for x in range(row_bytes):
                left = out[out_start + x - bpp] if x >= bpp else 0
                above = out[prev_start + x] if prev_start is not None else 0
                out[out_start + x] = (row[x] + ((left + above) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(row_bytes):
                a = out[out_start + x - bpp] if x >= bpp else 0
                b = out[prev_start + x] if prev_start is not None else 0
                c = (
                    out[prev_start + x - bpp]
                    if (prev_start is not None and x >= bpp)
                    else 0
                )
                out[out_start + x] = (row[x] + _paeth_predictor(a, b, c)) & 0xFF
        else:
            # Fallback for unexpected filter
            out[out_start : out_start + row_bytes] = row
    return out


def decode_png(data: bytes) -> tuple[int, int, bytearray]:
    """Decode standard PNG bytes into (width, height, rgba_bytearray)."""
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")

    if HAS_PIL:
        import io

        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return img.width, img.height, bytearray(img.tobytes())

    offset = 8
    width = 0
    height = 0
    bit_depth = 8
    color_type = 6
    idat_chunks: list[bytes] = []

    while offset < len(data):
        if offset + 8 > len(data):
            break
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        ctype = data[offset + 4 : offset + 8]
        cdata = data[offset + 8 : offset + 8 + length]
        offset += 12 + length

        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(
                ">IIBB", cdata[:10]
            )
        elif ctype == b"IDAT":
            idat_chunks.append(cdata)
        elif ctype == b"IEND":
            break

    if not idat_chunks or width == 0 or height == 0:
        raise ValueError("Incomplete or invalid PNG data")

    raw = zlib.decompress(b"".join(idat_chunks))

    if color_type == 6:  # RGBA
        bpp = 4
        unfiltered = _unfilter_scanlines(raw, width, height, bpp)
        return width, height, unfiltered
    elif color_type == 2:  # RGB -> convert to RGBA
        bpp = 3
        unfiltered = _unfilter_scanlines(raw, width, height, bpp)
        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            src_idx = i * 3
            dst_idx = i * 4
            rgba[dst_idx] = unfiltered[src_idx]
            rgba[dst_idx + 1] = unfiltered[src_idx + 1]
            rgba[dst_idx + 2] = unfiltered[src_idx + 2]
            rgba[dst_idx + 3] = 255
        return width, height, rgba
    elif color_type == 0:  # Grayscale -> RGBA
        bpp = 1
        unfiltered = _unfilter_scanlines(raw, width, height, bpp)
        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            g = unfiltered[i]
            dst_idx = i * 4
            rgba[dst_idx] = g
            rgba[dst_idx + 1] = g
            rgba[dst_idx + 2] = g
            rgba[dst_idx + 3] = 255
        return width, height, rgba
    else:
        raise ValueError(f"Unsupported PNG color type: {color_type}")


def encode_png(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """Encode RGBA byte buffer to PNG bytes."""
    if HAS_PIL:
        import io

        img = Image.frombytes("RGBA", (width, height), bytes(rgba))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    row_bytes = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # Filter 0: None
        start = y * row_bytes
        raw.extend(rgba[start : start + row_bytes])

    compressed = zlib.compress(bytes(raw), level=6)
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc

    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat_chunk = (
        struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    )

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend_chunk = struct.pack(">I", 0) + b"IEND" + iend_crc

    return b"\x89PNG\r\n\x1a\n" + ihdr_chunk + idat_chunk + iend_chunk


def _load_image_bytes(img_input: str | bytes) -> bytes:
    """Resolve file path, base64 data URI, or raw bytes into PNG bytes."""
    if isinstance(img_input, bytes):
        return img_input

    if not isinstance(img_input, str):
        raise TypeError(
            f"Expected image path, base64 data, or bytes, got {type(img_input).__name__}"
        )

    clean_str = img_input.strip()
    # Check if base64 data URI
    if clean_str.startswith("data:image/") and ";base64," in clean_str:
        b64_part = clean_str.split(";base64,")[1]
        return base64.b64decode(b64_part)

    # Check if file exists on disk
    if os.path.isfile(clean_str):
        with open(clean_str, "rb") as f:
            return f.read()

    # Try raw base64 decode
    try:
        decoded = base64.b64decode(clean_str)
        if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            return decoded
    except Exception:
        pass

    raise FileNotFoundError(
        f"Image file not found and string is not valid base64: {clean_str[:80]}..."
    )


def compare_screenshots(
    image1: str | bytes,
    image2: str | bytes,
    channel_threshold: int = 16,
    diff_output_path: str | None = None,
) -> dict[str, Any]:
    """Compare two screenshot images deterministically using RGBA pixel delta.

    Returns compact JSON metrics: status ('identical', 'different',
    'dimension_mismatch'), changed_pixels, changed_ratio,
    maximum_channel_delta, mean_channel_delta, bounding_box.
    """
    bytes1 = _load_image_bytes(image1)
    bytes2 = _load_image_bytes(image2)

    # Fast-path 1: exact binary equality (0.01 ms)
    if (
        bytes1 == bytes2
        or hashlib.sha256(bytes1).digest() == hashlib.sha256(bytes2).digest()
    ):
        w, h, _ = decode_png(bytes1)
        pixels = w * h
        return {
            "status": "identical",
            "compared_pixels": pixels,
            "changed_pixels": 0,
            "changed_ratio": 0.0,
            "maximum_channel_delta": 0,
            "mean_channel_delta": 0.0,
            "channel_threshold": channel_threshold,
            "dimensions": {"width": w, "height": h},
            "bounding_box": None,
            "diff_image_path": None,
        }

    w1, h1, rgba1 = decode_png(bytes1)
    w2, h2, rgba2 = decode_png(bytes2)

    if w1 != w2 or h1 != h2:
        return {
            "status": "dimension_mismatch",
            "compared_pixels": 0,
            "changed_pixels": None,
            "changed_ratio": None,
            "maximum_channel_delta": None,
            "mean_channel_delta": None,
            "channel_threshold": channel_threshold,
            "dimensions_1": {"width": w1, "height": h1},
            "dimensions_2": {"width": w2, "height": h2},
            "bounding_box": None,
            "diff_image_path": None,
        }

    total_pixels = w1 * h1
    changed_pixels = 0
    max_delta = 0
    total_delta = 0

    min_x = w1
    max_x = -1
    min_y = h1
    max_y = -1

    diff_rgba = bytearray(total_pixels * 4) if diff_output_path else None

    # Compare pixels
    for i in range(total_pixels):
        offset = i * 4
        r1, g1, b1, a1 = (
            rgba1[offset],
            rgba1[offset + 1],
            rgba1[offset + 2],
            rgba1[offset + 3],
        )
        r2, g2, b2, a2 = (
            rgba2[offset],
            rgba2[offset + 1],
            rgba2[offset + 2],
            rgba2[offset + 3],
        )

        dr = abs(r1 - r2)
        dg = abs(g1 - g2)
        db = abs(b1 - b2)
        da = abs(a1 - a2)

        pixel_max_delta = max(dr, dg, db, da)
        pixel_total_delta = dr + dg + db + da
        total_delta += pixel_total_delta
        if pixel_max_delta > max_delta:
            max_delta = pixel_max_delta

        is_changed = pixel_max_delta > channel_threshold
        if is_changed:
            changed_pixels += 1
            x = i % w1
            y = i // w1
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

            if diff_rgba is not None:
                # Highlight changed pixel in bright red
                diff_rgba[offset] = 255
                diff_rgba[offset + 1] = 0
                diff_rgba[offset + 2] = 0
                diff_rgba[offset + 3] = 255
        elif diff_rgba is not None:
            # Faded gray background for unchanged pixel
            gray = (r1 * 299 + g1 * 587 + b1 * 114) // 3000
            diff_rgba[offset] = gray
            diff_rgba[offset + 1] = gray
            diff_rgba[offset + 2] = gray
            diff_rgba[offset + 3] = 255

    mean_delta = total_delta / (total_pixels * 4) if total_pixels > 0 else 0.0

    bbox = None
    if changed_pixels > 0 and max_x >= min_x and max_y >= min_y:
        bbox = {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width": max_x - min_x + 1,
            "height": max_y - min_y + 1,
        }

    status = "identical" if changed_pixels == 0 else "different"

    if diff_output_path and diff_rgba is not None:
        diff_png = encode_png(w1, h1, diff_rgba)
        os.makedirs(os.path.dirname(os.path.abspath(diff_output_path)), exist_ok=True)
        with open(diff_output_path, "wb") as f:
            f.write(diff_png)

    return {
        "status": status,
        "compared_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "changed_ratio": round(changed_pixels / total_pixels, 6)
        if total_pixels > 0
        else 0.0,
        "maximum_channel_delta": max_delta,
        "mean_channel_delta": round(mean_delta, 4),
        "channel_threshold": channel_threshold,
        "dimensions": {"width": w1, "height": h1},
        "bounding_box": bbox,
        "diff_image_path": diff_output_path if diff_output_path else None,
    }
