"""Stream-copy MPEG-TS segments through PyAV to fix ExoPlayer audio.

Vavoo (and similar IPTV CDNs) sometimes serve TS segments with PMT/PCR
inconsistencies that ExoPlayer (Stremio Android / Fire TV) can't decode
audio from, even though the elementary AAC stream itself is valid.

PyAV's `mux()` regenerates PMT and PCR from scratch while doing pure
packet copy (no decode/encode). CPU cost is dominated by I/O — typically
under 5% per concurrent stream on a 1 vCPU instance, well within the
0.1 vCPU budget of Render free tier for 1-2 simultaneous viewers.

On any failure the original bytes are returned unchanged, so this is
safe to enable globally — no segment is ever lost.
"""

import asyncio
import io
import logging

import av

logger = logging.getLogger(__name__)


def _remux_ts_sync(input_bytes: bytes) -> bytes:
    in_buf = io.BytesIO(input_bytes)
    out_buf = io.BytesIO()

    in_container = av.open(in_buf, mode="r", format="mpegts")
    try:
        out_container = av.open(out_buf, mode="w", format="mpegts")
        try:
            stream_map: dict[int, av.stream.Stream] = {}
            for s in in_container.streams:
                if s.type in ("video", "audio"):
                    out_s = out_container.add_stream_from_template(s)
                    stream_map[s.index] = out_s

            if not stream_map:
                return input_bytes

            for packet in in_container.demux():
                if packet.dts is None:
                    continue
                out_s = stream_map.get(packet.stream.index)
                if out_s is None:
                    continue
                packet.stream = out_s
                out_container.mux(packet)
        finally:
            out_container.close()
    finally:
        in_container.close()

    remuxed = out_buf.getvalue()
    return remuxed if remuxed else input_bytes


async def remux_ts_for_exoplayer(input_bytes: bytes) -> bytes:
    """Async wrapper. Falls back to the original bytes on any error."""
    if not input_bytes:
        return input_bytes
    try:
        return await asyncio.to_thread(_remux_ts_sync, input_bytes)
    except Exception as e:
        logger.warning("Exoplayer TS remux failed (%s bytes): %s — passthrough", len(input_bytes), e)
        return input_bytes
