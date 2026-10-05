"""Synthetic MP4 container header for unit tests, not a playable video.

Real Supabase E2E requires a separate actual .mp4 file.
"""

MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42"
VIDEO_BYTES = MP4_HEADER + b"\x00\x00\x00\x0cmdat" + b"test"
