"""백엔드 공통 타입과 타임코드 유틸."""
from dataclasses import dataclass


class VideoSearchError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패(파일 없음, 크기 초과, 키 없음 등)."""


@dataclass
class Moment:
    start_sec: float
    end_sec: float
    confidence: str = ""  # 백엔드가 주는 경우만 (Gemini: high/medium/low)
    reason: str = ""


def parse_timecode(tc: str) -> float:
    """'HH:MM:SS', 'MM:SS', 'SS' (소수 초 허용)를 초로 변환한다."""
    parts = tc.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"타임코드 형식 오류: {tc!r}")
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
    except ValueError:
        raise ValueError(f"타임코드 형식 오류: {tc!r}") from None
    return seconds


def format_timecode(seconds: float) -> str:
    """초를 hh:mm:ss로 변환한다. 1시간 미만이면 mm:ss."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
