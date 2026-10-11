"""evaluate.py가 남긴 기록(results/*.json)으로 지표를 계산해 프로필끼리 비교한다.

    python report.py                                  # results/의 모든 실행 (같은 프로필은 케이스별 최신 성공 기록으로 합침)
    python report.py results/a.json results/b.json    # 지정한 실행들
    python report.py --separate                       # 합치지 않고 실행마다 따로
    python report.py --review review.csv              # 정성 검토용 시트도 저장
    python report.py --testset testsets/other.json    # 다른 테스트셋 파일의 정답으로 계산

정답은 기본으로 각 실행이 쓴 테스트셋 파일의 현재 내용에서 읽으므로, 정답을 고치고 다시 돌리면 바로 반영된다.

지표 정의는 README 참고.
"""
import argparse
import csv
import glob
import json
import math
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import config
from common import format_timecode
from testset import Case, load_testset

IOU_THRESHOLDS = (0.3, 0.5, 0.7)
MAIN_IOU = 0.5    # 디코이 정답률, 반복 일관성(정답 여부)에 쓰는 기준
DECOY_IOU = 0.3   # top-1이 디코이와 이 이상 겹치고 정답보다 더 겹치면 디코이에 속은 것으로 본다


@dataclass
class Run:
    path: Path
    label: str
    data: dict
    cases: dict[str, Case]

    @property
    def records(self) -> list[dict]:
        return [r for r in self.data["records"] if r["case_id"] in self.cases]

    @property
    def profile(self) -> dict:
        return self.data["profile"]

    @property
    def testset_key(self) -> str:
        """실행에 쓴 테스트셋 (절대경로). 테스트셋이 다르면 결과를 합치지 않는다."""
        found = _find_testset(self.data.get("testset"))
        return str(found.resolve()) if found else self.data.get("testset", "")


def load_run(path: Path, testset_path: Path | None = None) -> Run:
    """정답은 --testset 파일 → 실행 때 쓴 테스트셋 파일(현재 내용) → 기록에 남은 사본 순으로 찾는다.

    정답을 고친 뒤 다시 돌리면 API 재호출 없이 바로 반영되도록 현재 파일을 우선한다.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    testset_path = testset_path or _find_testset(data.get("testset"))
    if testset_path:
        meta, cases = load_testset(testset_path)
        data["youtube_url"] = meta["youtube_url"] or data.get("youtube_url", "")
        known = {c.id for c in cases}
        # 테스트셋에서 지워진 케이스는 기록의 사본으로 남긴다
        cases += [_snapshot_case(c) for c in data["cases"] if c["id"] not in known]
    else:
        cases = [_snapshot_case(c) for c in data["cases"]]
    recorded = {r["case_id"] for r in data["records"]}
    return Run(Path(path), data["profile_name"], data, {c.id: c for c in cases if c.id in recorded})


def _find_testset(recorded_path: str | None) -> Path | None:
    if not recorded_path:
        return None
    for candidate in (Path(recorded_path), config.ROOT / recorded_path):  # 실행 위치 기준 상대경로일 수 있음
        if candidate.is_file():
            return candidate
    return None


def _snapshot_case(c: dict) -> Case:
    return Case(**{**c, "gt": _tuples(c["gt"]), "decoys": _tuples(c["decoys"])})


def _tuples(segments):
    return None if segments is None else [tuple(s) for s in segments]


# ---- 구간 계산 ----

def iou(a, b) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def best_iou(pred, segments) -> tuple[float, int]:
    """pred와 가장 많이 겹치는 구간의 (IoU, 인덱스). segments가 비면 (0, -1)."""
    scores = [iou(pred, s) for s in segments]
    return (max(scores), scores.index(max(scores))) if scores else (0.0, -1)


def preds(record) -> list[tuple[float, float]]:
    return [(m["start_sec"], m["end_sec"]) for m in record.get("moments") or []]


def fooled_by_decoy(case: Case, record) -> bool:
    if not case.decoys or not preds(record):
        return False
    top = preds(record)[0]
    decoy_score = best_iou(top, case.decoys)[0]
    return decoy_score >= DECOY_IOU and decoy_score > best_iou(top, case.gt)[0]


# ---- 비용 ----

def _modality_tokens(details, modality: str) -> int:
    return sum(d.get("token_count", 0) for d in details or [] if d.get("modality") == modality)


def query_cost(profile: dict, usage: dict) -> float | None:
    """응답에 찍힌 실제 사용량 × config 단가. 단가가 없으면 None."""
    if profile["backend"] == "twelvelabs":
        return usage.get("search_queries", 0) * config.TL_PRICING["search_per_query"]
    price = config.GEMINI_PRICING.get(profile["model"])
    if price is None or "prompt_token_count" not in usage:
        return None
    prompt = usage.get("prompt_token_count", 0)
    # agentic 처리에서 모델이 도구 호출로 불러온 영상 구간은 여기에 잡힌다. 입력 단가로 과금된다.
    tool_prompt = usage.get("tool_use_prompt_token_count", 0)
    cached = usage.get("cached_content_token_count", 0)
    audio = (_modality_tokens(usage.get("prompt_tokens_details"), "AUDIO")
             + _modality_tokens(usage.get("tool_use_prompt_tokens_details"), "AUDIO"))
    audio_uncached = max(0, audio - _modality_tokens(usage.get("cache_tokens_details"), "AUDIO"))
    other_uncached = max(0, prompt + tool_prompt - cached - audio_uncached)
    output = usage.get("candidates_token_count", 0) + usage.get("thoughts_token_count", 0)

    long = prompt + tool_prompt > price.get("long_threshold", math.inf)
    unit = lambda key: price[f"{key}_long"] if long and f"{key}_long" in price else price[key]
    audio_unit = price.get("input_audio", unit("input"))
    return (other_uncached * unit("input") + audio_uncached * audio_unit
            + cached * unit("cached") + output * unit("output")) / 1e6


def prepare_cost(profile: dict, info: dict | None) -> float:
    """TwelveLabs 인덱싱 비용 (이번 실행에서 새로 인덱싱한 경우만). Gemini 업로드는 무료."""
    if profile["backend"] == "twelvelabs" and info and not info.get("reused") and info.get("duration_sec"):
        return info["duration_sec"] / 3600 * config.TL_PRICING["index_per_hour"]
    return 0.0


# ---- 지표 ----

def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _percentile(xs, p):
    xs = sorted(xs)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


def _pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def _num(x, digits=2):
    return "-" if x is None else f"{x:,.{digits}f}"


def _money(x):
    return "-" if x is None else f"${x:.4f}"


def _consistency(run: Run) -> tuple[float | None, float | None]:
    """반복 질의 간 (top-1 pairwise IoU 평균, 정답 여부가 모두 같은 케이스 비율)."""
    by_case: dict[str, list[dict]] = {}
    for r in run.records:
        if r["status"] == "ok":
            by_case.setdefault(r["case_id"], []).append(r)
    pair_scores, agree = [], []
    for case_id, recs in by_case.items():
        if len(recs) < 2:
            continue
        case = run.cases[case_id]
        tops = [preds(r)[:1] for r in recs]
        scores = []
        for i in range(len(tops)):
            for j in range(i + 1, len(tops)):
                a, b = tops[i], tops[j]
                scores.append(1.0 if not a and not b else 0.0 if not a or not b else iou(a[0], b[0]))
        pair_scores.append(_mean(scores))
        if case.kind == "unlabeled":
            continue
        if case.kind == "negative":
            outcomes = [not preds(r) for r in recs]
        else:
            outcomes = [bool(preds(r)) and best_iou(preds(r)[0], case.gt)[0] >= MAIN_IOU for r in recs]
        agree.append(1.0 if len(set(outcomes)) == 1 else 0.0)
    return _mean(pair_scores), _mean(agree)


def compute_metrics(run: Run) -> list[tuple[str, str, str]]:
    """(섹션, 지표, 값) 목록. 모든 실행이 같은 순서·같은 이름의 행을 낸다."""
    profile, records = run.profile, run.records
    ok = [r for r in records if r["status"] == "ok"]
    kind = lambda r: run.cases[r["case_id"]].kind
    gt = lambda r: run.cases[r["case_id"]].gt
    pos = [r for r in ok if kind(r) in ("normal", "decoy")]
    dec = [r for r in ok if kind(r) == "decoy"]
    neg = [r for r in ok if kind(r) == "negative"]
    rows = []
    add = lambda section, label, value: rows.append((section, label, value))

    add("설정", "백엔드 / 모델", f"{profile['backend']} / {profile['model']}")
    is_gemini = profile["backend"] == "gemini"
    add("설정", "처리 모드 / 해상도",
        f"{profile.get('processing', '기본값')} / {profile.get('media_resolution', 'low')}" if is_gemini else "-")
    add("설정", "반복 / K(최대 후보)", f"{run.data['repeats']} / {run.data['max_matches']}")
    add("설정", "질의 수 (성공/전체)", f"{len(ok)}/{len(records)}")
    add("설정", "정답 미입력 질의 수", str(sum(kind(r) == "unlabeled" for r in records)))

    # 정확도: 정답이 있는 케이스(normal + decoy)
    top1_iou = [best_iou(preds(r)[0], gt(r))[0] if preds(r) else 0.0 for r in pos]
    any_iou = [max((best_iou(p, gt(r))[0] for p in preds(r)), default=0.0) for r in pos]
    add("정확도", "대상 질의 수", str(len(pos)))
    for t in IOU_THRESHOLDS:
        add("정확도", f"R@1 IoU≥{t}", _pct(_mean(x >= t for x in top1_iou)))
    for t in IOU_THRESHOLDS:
        add("정확도", f"R@{run.data['max_matches']} IoU≥{t}", _pct(_mean(x >= t for x in any_iou)))
    add("정확도", "mIoU@1", _num(_mean(top1_iou), 3))

    # 경계 오차: top-1이 정답 구간과 겹친 경우만, 가장 많이 겹친 정답 구간 기준
    d_start, d_end = [], []
    for r in pos:
        if not preds(r):
            continue
        top = preds(r)[0]
        score, idx = best_iou(top, gt(r))
        if score > 0:
            d_start.append(abs(top[0] - gt(r)[idx][0]))
            d_end.append(abs(top[1] - gt(r)[idx][1]))
    median = lambda xs: statistics.median(xs) if xs else None
    add("경계 오차", "대상 질의 수 (top-1이 정답과 겹침)", str(len(d_start)))
    add("경계 오차", "시작 오차 평균 / 중앙값 (초)", f"{_num(_mean(d_start), 1)} / {_num(median(d_start), 1)}")
    add("경계 오차", "끝 오차 평균 / 중앙값 (초)", f"{_num(_mean(d_end), 1)} / {_num(median(d_end), 1)}")

    # 디코이
    add("디코이", "대상 질의 수", str(len(dec)))
    add("디코이", f"R@1 IoU≥{MAIN_IOU}", _pct(_mean(
        bool(preds(r)) and best_iou(preds(r)[0], gt(r))[0] >= MAIN_IOU for r in dec)))
    add("디코이", "디코이 오인율@1", _pct(_mean(fooled_by_decoy(run.cases[r["case_id"]], r) for r in dec)))

    # 없음 처리
    add("없음 처리", "대상 질의 수", str(len(neg)))
    add("없음 처리", "'못 찾음' 응답률", _pct(_mean(not preds(r) for r in neg)))

    # 비용
    costs = [query_cost(profile, r.get("usage") or {}) for r in ok]
    known = [c for c in costs if c is not None]
    usages = [r.get("usage") or {} for r in ok]
    tok = lambda key: _num(_mean(u.get(key, 0) for u in usages if "prompt_token_count" in u), 0)
    prep_cost = sum(prepare_cost(profile, p.get("info")) for p in run.data["prepare"])
    add("비용", "질의당 평균 ($)", _money(_mean(known)) if len(known) == len(costs) else "단가 없음")
    add("비용", "질의 합계 ($)", _money(sum(known)) if len(known) == len(costs) else "단가 없음")
    add("비용", "준비 비용 ($, 인덱싱)", _money(prep_cost))
    add("비용", "입력 토큰 / 질의", tok("prompt_token_count"))
    add("비용", "  └ 캐시 적중 토큰", tok("cached_content_token_count"))
    add("비용", "도구 호출 입력 토큰 / 질의 (agentic 영상 탐색)", tok("tool_use_prompt_token_count"))
    add("비용", "출력 토큰 / 질의", tok("candidates_token_count"))
    add("비용", "thinking 토큰 / 질의", tok("thoughts_token_count"))

    # 속도
    lat = [r["latency_sec"] for r in ok]
    add("속도", "질의 지연 평균 (초)", _num(_mean(lat), 1))
    add("속도", "질의 지연 p50 / p95 / 최대 (초)",
        f"{_num(_percentile(lat, 50), 1)} / {_num(_percentile(lat, 95), 1)} / {_num(max(lat) if lat else None, 1)}")
    add("속도", "준비 시간 (초, 영상 1개 업로드·인덱싱 평균)", _num(_mean(p["seconds"] for p in run.data["prepare"]), 1))

    # 출력 안정성
    pair_iou, agree = _consistency(run)
    add("안정성", "API 오류율 (재시도 후 최종 실패)", _pct(_mean(r["status"] != "ok" for r in records)))
    add("안정성", "일시 오류로 재시도한 질의 비율", _pct(_mean(r.get("attempts", 1) > 1 for r in records)))
    add("안정성", "형식 준수율", _pct(_mean(not r.get("format_issues") for r in ok)))
    add("안정성", "반복 일관성: top-1 IoU", _num(pair_iou, 3))
    add("안정성", "반복 일관성: 정답 여부 일치", _pct(agree))
    return rows


# ---- 출력 ----

def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _fit(s: str, width: int) -> str:
    if _width(s) > width:
        while _width(s) > width - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (width - _width(s))


def _table(header: list[str], rows: list[list[str]], widths: list[int]) -> None:
    print(" | ".join(_fit(h, w) for h, w in zip(header, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(_fit(c, w) for c, w in zip(row, widths)))


def print_report(runs: list[Run]) -> None:
    metrics = [compute_metrics(r) for r in runs]
    rows = [[f"[{s}] {label}" if i == 0 or metrics[0][i - 1][0] != s else f"  {label}"]
            + [m[i][2] for m in metrics]
            for i, (s, label, _) in enumerate(metrics[0])]
    header = ["지표"] + [r.label for r in runs]
    widths = [max(_width(row[i]) for row in rows + [header]) for i in range(len(header))]
    print()
    _table(header, rows, widths)

    # 케이스별: 정답 있는 케이스는 top-1 IoU 평균(디코이에 속은 횟수), 정답 없는 케이스는 '못 찾음' 횟수
    case_ids = list(dict.fromkeys(cid for r in runs for cid in r.cases))
    rows = []
    for cid in case_ids:
        case = next(r.cases[cid] for r in runs if cid in r.cases)
        row = [cid, case.kind, case.query]
        for run in runs:
            recs = [r for r in run.records if r["case_id"] == cid]
            ok = [r for r in recs if r["status"] == "ok"]
            if not recs:
                row.append("-")
            elif not ok:
                row.append(f"오류 {len(recs)}")
            elif case.kind == "unlabeled":  # 정답이 없으니 첫 응답의 1순위를 보여준다 (정답 잡을 때 참고용)
                top = preds(ok[0])[:1]
                row.append(f"1순위 {_segments_text(top)}" if top else "결과 없음")
            elif case.kind == "negative":
                row.append(f"못찾음 {sum(not preds(r) for r in ok)}/{len(ok)}")
            else:
                ious = [best_iou(preds(r)[0], case.gt)[0] if preds(r) else 0.0 for r in ok]
                cell = f"{_mean(ious):.2f}"
                if case.decoys:
                    cell += f" 디코이{sum(fooled_by_decoy(case, r) for r in ok)}"
                if len(ok) < len(recs):
                    cell += f" 오류{len(recs) - len(ok)}"
                row.append(cell)
        rows.append(row)
    print("\n케이스별 (정답 있음: top-1 IoU 평균 / 정답 없음: '못 찾음' 응답 횟수 / 정답 미입력: 첫 응답의 1순위)\n")
    header = ["id", "유형", "쿼리"] + [r.label for r in runs]
    widths = [max(_width(row[i]) for row in rows + [header]) for i in range(len(header))]
    widths[2] = min(widths[2], 24)  # 쿼리는 길면 자른다
    _table(header, rows, widths)

    print("\n* 비용 = 응답에 찍힌 실제 사용량(토큰 수, 검색 횟수) × config.py 단가. 단가는 공식 가격표로 확인할 것.")
    if any(r.profile["backend"] == "twelvelabs" for r in runs):
        print("* TwelveLabs 검색은 항상 결과를 돌려주므로 '못 찾음' 응답률이 구조적으로 0%다.")


def _segments_text(segments) -> str:
    if segments is None:
        return "(미입력)"
    return ", ".join(f"{format_timecode(s)}~{format_timecode(e)}" for s, e in segments) if segments else "(없음)"


def _youtube_link(url: str, seconds: float) -> str:
    if not url:
        return ""
    return f"{url}{'&' if '?' in url else '?'}t={int(seconds)}"


def write_review(runs: list[Run], path: Path) -> None:
    """케이스 × 프로필의 첫 성공 질의 결과를 후보별 한 줄로 쓴다. 판정/메모 칸은 직접 채운다."""
    header = ["case_id", "유형", "쿼리", "정답", "디코이", "프로필", "순위", "예측", "IoU",
              "신뢰도", "근거", "링크", "판정", "메모"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀 한글 깨짐 방지
        writer = csv.writer(f)
        writer.writerow(header)
        for run in runs:
            for cid, case in run.cases.items():
                url = case.youtube_url or run.data.get("youtube_url", "")
                record = next((r for r in run.records if r["case_id"] == cid and r["status"] == "ok"), None)
                if record is None:
                    continue
                base = [cid, case.kind, case.query, _segments_text(case.gt), _segments_text(case.decoys), run.label]
                if not record["moments"]:
                    writer.writerow(base + ["-", "(결과 없음)", "", "", "", "", "", ""])
                for rank, m in enumerate(record["moments"], 1):
                    pred = (m["start_sec"], m["end_sec"])
                    writer.writerow(base + [
                        rank, _segments_text([pred]), f"{best_iou(pred, case.gt)[0]:.2f}" if case.gt is not None else "",
                        m.get("confidence", ""), m.get("reason", ""), _youtube_link(url, pred[0]), "", "",
                    ])


def _collect(args_paths: list[str]) -> list[Path]:
    """인자가 없으면 results/의 모든 실행."""
    if not args_paths:
        return sorted(config.RESULTS_DIR.glob("*.json"))
    paths = []
    for arg in args_paths:  # PowerShell은 와일드카드를 펼쳐주지 않으므로 직접 처리
        p = Path(arg)
        found = sorted(p.glob("*.json")) if p.is_dir() else [Path(x) for x in sorted(glob.glob(arg))]
        if not found:
            print(f"결과 파일 없음: {arg}", file=sys.stderr)
        paths += found
    return paths


def merge_runs(runs: list[Run]) -> list[Run]:
    """이름과 설정이 같은 프로필의 실행들을 하나로 합친다.

    케이스마다 성공 기록이 있는 가장 최근 실행의 기록(그 실행의 반복 전부)을 쓴다.
    성공 기록이 없으면 그 케이스가 있는 가장 최근 실행의 기록을 쓴다.
    그래서 실패한 실행이나 일부 케이스만 다시 돌린 실행이 섞여 있어도 케이스별로 최신 성공 결과가 모인다.
    """
    groups: dict[tuple, list[Run]] = {}
    for run in runs:
        key = (run.testset_key, run.data["profile_name"], json.dumps(run.profile, sort_keys=True))
        groups.setdefault(key, []).append(run)

    merged = []
    for group in groups.values():
        group.sort(key=lambda r: r.data["started_at"])
        if len(group) == 1:
            merged.append(group[0])
            continue
        records, cases, used = [], {}, []
        for cid in dict.fromkeys(cid for r in group for cid in r.cases):
            has = lambda r, ok: any(x["case_id"] == cid and (x["status"] == "ok" or not ok) for x in r.data["records"])
            src = (next((r for r in reversed(group) if has(r, True)), None)
                   or next(r for r in reversed(group) if has(r, False)))
            records += [x for x in src.data["records"] if x["case_id"] == cid]
            cases[cid] = src.cases[cid]
            if src not in used:
                used.append(src)
        latest = group[-1]
        data = {**latest.data, "records": records,
                "prepare": [p for r in used for p in r.data["prepare"]],
                "repeats": max(r.data["repeats"] for r in used),
                "merged_from": [r.path.name for r in used]}
        merged.append(Run(latest.path, latest.label, data, cases))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="평가 기록으로 프로필별 지표를 비교한다.")
    parser.add_argument("results", nargs="*", help="결과 JSON 파일/폴더 (기본: results/의 모든 실행)")
    parser.add_argument("--testset", type=Path,
                        help="정답을 이 테스트셋에서 읽음 (기본: 각 실행이 쓴 테스트셋 파일의 현재 내용)")
    parser.add_argument("--review", type=Path, help="정성 검토용 CSV 저장 경로")
    parser.add_argument("--separate", action="store_true",
                        help="같은 프로필의 실행을 합치지 않고 실행마다 따로 보기 (설정 변경 전후 비교 등)")
    args = parser.parse_args()

    paths = _collect(args.results)
    if not paths:
        print("결과 파일이 없습니다. 먼저 evaluate.py를 실행하세요.", file=sys.stderr)
        return 1
    runs = [load_run(p) for p in paths]
    if args.testset:  # 이 테스트셋으로 돌린 실행만, 정답도 이 파일에서
        wanted = str(args.testset.resolve())
        runs = [load_run(r.path, args.testset) for r in runs if r.testset_key == wanted]
        if not runs:
            print(f"{args.testset}로 돌린 실행 기록이 없습니다.", file=sys.stderr)
            return 1
    if not args.separate:
        runs = merge_runs(runs)

    # 테스트셋이 다르면 지표를 섞지 않고 테스트셋별로 따로 출력한다
    by_testset: dict[str, list[Run]] = {}
    for run in runs:
        by_testset.setdefault(run.testset_key, []).append(run)
    for key, group in by_testset.items():
        if len(by_testset) > 1:
            print(f"\n{'=' * 20} 테스트셋: {Path(key).name} ({len(group)}개 프로필) {'=' * 20}")
        # 같은 프로필 이름이 여러 열이면(설정이 다르거나 --separate) 시작 시각으로 구분
        labels = [r.label for r in group]
        for r in group:
            if labels.count(r.label) > 1:
                r.label = f"{r.label}@{r.data['started_at'][5:16]}"
        print_report(group)
        if args.review:
            path = args.review if len(by_testset) == 1 else \
                args.review.with_name(f"{args.review.stem}_{Path(key).stem}{args.review.suffix}")
            write_review(group, path)
            print(f"\n정성 검토 시트 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
