"""ExoPlayer compatibility remux: video copy + audio reencode to 48 kHz AAC.

Vavoo (and similar IPTV CDNs) often serve TS segments with audio at 44.1 kHz
AAC. ExoPlayer hardware decoders on Fire TV / Android TV silently fail on
44.1 kHz live TS — no sound, no error. Resampling to 48 kHz fixes it.

Implementation: ffmpeg subprocess (`-c:v copy -c:a aac -ar 48000 -ac 2`).
ffmpeg native is ~5x faster than PyAV for this work — the difference matters
on Render free tier's 0.1 vCPU. Local benchmark on a 2.2 MB ARTE segment:
PyAV 366 ms vs ffmpeg 80 ms.

The function is fail-safe: any error returns the original bytes unchanged,
so EXOPLAYER_REMUX=true cannot break existing channels.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_FFMPEG_TIMEOUT_S = 30


async def remux_ts_for_exoplayer(input_bytes: bytes) -> bytes:
    """Pipe a TS segment through ffmpeg: video copy + audio reencode @ 48 kHz."""
    if not input_bytes:
        return input_bytes

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "128k",
        "-f", "mpegts",
        "pipe:1",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffmpeg not found in PATH — falling back to passthrough")
        return input_bytes

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=input_bytes), timeout=_FFMPEG_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("Exoplayer remux timeout (%ss) for %d bytes — passthrough", _FFMPEG_TIMEOUT_S, len(input_bytes))
        return input_bytes
    except Exception as e:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        logger.warning("Exoplayer remux error (%d bytes): %s — passthrough", len(input_bytes), e)
        return input_bytes

    if proc.returncode != 0 or not stdout:
        err_preview = (stderr or b"")[:300].decode("utf-8", "replace").strip()
        logger.warning(
            "Exoplayer remux exit=%s stdout=%d bytes; stderr: %s — passthrough",
            proc.returncode, len(stdout), err_preview,
        )
        return input_bytes

    return stdout
