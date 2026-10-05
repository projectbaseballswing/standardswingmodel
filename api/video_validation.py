"""가벼운 컨테이너 헤더 검사. 디코딩/스윙 유효성은 기존 파이프라인에서 검사한다."""

from pathlib import Path

from fastapi import HTTPException

VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
               ".mkv": "video/x-matroska", ".m4v": "video/x-m4v"}
MIME_ALIASES = {".mp4": {"application/mp4"}, ".mov": {"video/mov", "video/x-quicktime"},
                ".avi": {"video/avi"}, ".mkv": {"video/matroska"}, ".m4v": {"video/mp4"}}


def video_type(filename: str, content_type: str | None) -> tuple[str, str]:
    if not filename or any(char in filename for char in ("/", "\\", "\x00")):
        raise HTTPException(415, "영상 파일명에 경로를 포함할 수 없습니다.")
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_TYPES:
        raise HTTPException(415, "지원하지 않는 영상 확장자입니다.")
    mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime == "application/octet-stream":
        mime = VIDEO_TYPES[suffix]
    if mime not in {VIDEO_TYPES[suffix], *MIME_ALIASES[suffix]}:
        raise HTTPException(415, "영상 확장자와 Content-Type을 확인하세요.")
    return suffix, mime


def validate_video_header(path: str, suffix: str) -> None:
    with open(path, "rb") as stream:
        head = stream.read(32)
    size = Path(path).stat().st_size
    if suffix == ".avi":
        valid = len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI "
    elif suffix == ".mkv":
        valid = len(head) >= 8 and head[:4] == b"\x1a\x45\xdf\xa3"
    else:
        box_size = int.from_bytes(head[:4], "big")
        box_types = {b"ftyp"} if suffix != ".mov" else {b"ftyp", b"moov", b"mdat", b"wide", b"free"}
        valid = len(head) >= 12 and head[4:8] in box_types and (box_size == 0 or 8 <= box_size <= size)
        if head[4:8] == b"ftyp":
            valid = valid and box_size >= 16
    if not valid:
        raise HTTPException(415, "영상 컨테이너 헤더를 확인할 수 없습니다. 실제 영상 파일을 업로드하세요.")
