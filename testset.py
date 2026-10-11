"""테스트셋 JSON 읽기와 검증.

케이스 유형은 정답/디코이 입력으로 정해진다.
- normal   : gt에 구간이 있고 decoys가 비어 있음
- decoy    : gt와 함께 헷갈리는 구간(decoys)이 있음
- negative : gt가 빈 리스트 [] (영상에 없는 장면)
- unlabeled: gt가 null (정답 미입력). 실행은 하지만 정확도 지표에서는 빠지고 비용·속도·안정성에만 들어간다.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from common import parse_time

Segment = tuple[float, float]


@dataclass
class Case:
    id: str
    query: str
    video: str                   # 절대경로 문자열
    gt: list[Segment] | None     # [] = 정답 없음, None = 미입력
    decoys: list[Segment] = field(default_factory=list)
    note: str = ""
    skip_reason: str = ""
    youtube_url: str = ""        # 검토 시트의 시점 링크용 (케이스별, 없으면 테스트셋 최상위 값)

    @property
    def kind(self) -> str:
        if self.gt is None:
            return "unlabeled"
        if self.gt == []:
            return "negative"
        return "decoy" if self.decoys else "normal"


def _segments(raw, label: str) -> list[Segment]:
    if not isinstance(raw, list):
        raise ValueError(f"{label}는 [[시작, 끝], ...] 형식이어야 함")
    if len(raw) == 2 and not any(isinstance(x, list) for x in raw):
        raw = [raw]  # 구간 하나를 [시작, 끝]으로 적은 경우
    segments = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 2):
            raise ValueError(f"{label} 항목 형식 오류: {item!r}")
        start, end = parse_time(item[0]), parse_time(item[1])
        if end <= start:
            raise ValueError(f"{label} 구간의 끝이 시작보다 커야 함: {item!r}")
        segments.append((start, end))
    return segments


def _load_case(raw: dict, default_video: str | None, default_url: str, base_dir: Path) -> Case:
    case = Case(id=str(raw.get("id", "?")), query=raw.get("query") or "", video="", gt=None,
                note=raw.get("note", ""), youtube_url=raw.get("youtube_url") or default_url)
    video = raw.get("video") or default_video or ""
    path = Path(video)
    case.video = str(path if path.is_absolute() else (base_dir / path).resolve())
    try:
        if not case.query:
            raise ValueError("query 미입력")
        if raw.get("gt") is not None:
            case.gt = _segments(raw["gt"], "gt")
        case.decoys = _segments(raw.get("decoys") or [], "decoys")
        if not video:
            raise ValueError("video 미입력")
        if not Path(case.video).is_file():
            raise ValueError(f"영상 파일 없음: {case.video}")
    except ValueError as e:
        case.skip_reason = str(e)
    return case


def load_testset(path: Path) -> tuple[dict, list[Case]]:
    """(메타데이터, 케이스 목록)을 돌려준다. 실행할 수 없는 케이스는 skip_reason이 채워진다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.resolve().parent
    meta = {"youtube_url": data.get("youtube_url") or ""}
    cases = [_load_case(c, data.get("video"), meta["youtube_url"], base_dir) for c in data.get("cases", [])]
    return meta, cases
