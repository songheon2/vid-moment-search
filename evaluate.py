"""테스트셋(JSON)의 케이스를 일괄 실행하고 정답 구간과의 IoU를 표로 출력한다.

    python evaluate.py testsets/template.json [--backend gemini|twelvelabs] [--model MODEL]

- IoU@1   : 1순위 후보와 정답 구간의 IoU
- best IoU: 모든 후보 중 가장 높은 IoU
- 영상 경로가 상대경로면 테스트셋 파일 위치 기준으로 해석한다.
"""
import argparse
import json
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from backends import NAMES, get_backend
from common import Moment, VideoSearchError, format_timecode


@dataclass
class CaseResult:
    case_id: str
    query: str
    gt: tuple[float, float] | None
    moments: list[Moment] | None = None
    elapsed: float | None = None
    status: str = "OK"  # OK / SKIP / ERROR
    message: str = ""

    @property
    def iou_top1(self) -> float | None:
        if self.status != "OK":
            return None
        return iou(self.moments[0], self.gt) if self.moments else 0.0

    @property
    def iou_best(self) -> float | None:
        if self.status != "OK":
            return None
        return max((iou(m, self.gt) for m in self.moments), default=0.0)


def iou(pred: Moment, gt: tuple[float, float]) -> float:
    gt_start, gt_end = gt
    inter = max(0.0, min(pred.end_sec, gt_end) - max(pred.start_sec, gt_start))
    union = (pred.end_sec - pred.start_sec) + (gt_end - gt_start) - inter
    return inter / union if union > 0 else 0.0


def validate_case(case: dict, base_dir: Path) -> tuple[Path, tuple[float, float]]:
    """케이스가 실행 가능한지 확인한다. 아니면 SKIP 사유를 담아 ValueError."""
    if not case.get("query"):
        raise ValueError("query 미입력")
    gt_start, gt_end = case.get("gt_start"), case.get("gt_end")
    if not isinstance(gt_start, (int, float)) or not isinstance(gt_end, (int, float)):
        raise ValueError("gt_start/gt_end 미입력")
    if gt_end <= gt_start:
        raise ValueError("gt_end가 gt_start보다 커야 함")
    video = Path(case.get("video") or "")
    if not video.is_absolute():
        video = base_dir / video
    if not video.is_file():
        raise ValueError(f"영상 파일 없음: {video}")
    return video, (float(gt_start), float(gt_end))


def run_case(backend, client, case: dict, base_dir: Path, model: str) -> CaseResult:
    result = CaseResult(case_id=str(case.get("id", "?")), query=case.get("query", ""), gt=None)
    try:
        video, result.gt = validate_case(case, base_dir)
    except ValueError as e:
        result.status, result.message = "SKIP", str(e)
        return result

    print(f"\n=== {result.case_id}: {result.query}", file=sys.stderr)
    started = time.monotonic()
    try:
        result.moments = backend.search_moments(client, video, result.query, model)
    except Exception as e:  # 한 케이스 실패가 전체 평가를 멈추지 않게
        result.status, result.message = "ERROR", f"{type(e).__name__}: {e}"
    result.elapsed = time.monotonic() - started
    return result


# ---- 표 출력 (한글 폭 2칸 고려) ----

def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _fit(s: str, width: int) -> str:
    if _width(s) > width:
        while _width(s) > width - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (width - _width(s))


def _span(start: float, end: float) -> str:
    return f"{format_timecode(start)}~{format_timecode(end)}"


def _num(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


def print_table(results: list[CaseResult], backend_name: str, model: str) -> None:
    columns = [("id", 10), ("query", 28), ("GT", 13), ("pred@1", 13),
               ("IoU@1", 7), ("best IoU", 8), ("#cand", 5), ("sec", 6), ("status", 6)]
    header = " | ".join(_fit(name, w) for name, w in columns)
    rule = "-+-".join("-" * w for _, w in columns)

    print(f"\n백엔드: {backend_name} / 모델: {model}\n")
    print(header)
    print(rule)
    for r in results:
        top1 = r.moments[0] if r.moments else None
        cells = [
            r.case_id,
            r.query,
            _span(*r.gt) if r.gt else "-",
            _span(top1.start_sec, top1.end_sec) if top1 else "-",
            _num(r.iou_top1),
            _num(r.iou_best),
            str(len(r.moments)) if r.moments is not None else "-",
            f"{r.elapsed:.1f}" if r.elapsed is not None else "-",
            r.status,
        ]
        print(" | ".join(_fit(c, w) for c, (_, w) in zip(cells, columns)))
    print(rule)

    ok = [r for r in results if r.status == "OK"]
    if ok:
        mean_top1 = sum(r.iou_top1 for r in ok) / len(ok)
        mean_best = sum(r.iou_best for r in ok) / len(ok)
        cells = [f"평균(n={len(ok)})", "", "", "", _num(mean_top1), _num(mean_best), "", "", ""]
        print(" | ".join(_fit(c, w) for c, (_, w) in zip(cells, columns)))

    problems = [r for r in results if r.status != "OK"]
    if problems:
        print("\n평균에서 제외된 케이스:")
        for r in problems:
            print(f"  [{r.status}] {r.case_id}: {r.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="테스트셋으로 장면 검색 IoU를 평가한다.")
    parser.add_argument("testset", type=Path, help="테스트셋 JSON 경로")
    parser.add_argument("--backend", choices=NAMES, default="gemini", help="검색 백엔드 (기본: gemini)")
    parser.add_argument("--model", help="모델 ID (기본: 백엔드별 config 값)")
    args = parser.parse_args()

    backend = get_backend(args.backend)
    model = args.model or backend.DEFAULT_MODEL

    cases = json.loads(args.testset.read_text(encoding="utf-8"))["cases"]
    base_dir = args.testset.resolve().parent

    def runnable(case: dict) -> bool:
        try:
            validate_case(case, base_dir)
            return True
        except ValueError:
            return False

    client = None
    if any(runnable(c) for c in cases):  # 실행할 케이스가 있을 때만 API 키 요구
        try:
            client = backend.make_client()
        except VideoSearchError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1

    results = [run_case(backend, client, case, base_dir, model) for case in cases]
    print_table(results, args.backend, model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
