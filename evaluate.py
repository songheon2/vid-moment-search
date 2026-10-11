"""테스트셋을 프로필별로 실행하고 모든 질의 기록을 results/에 저장한다.

    python evaluate.py testsets/camping.json --profile gemini-3.1-pro --profile gemini-3.8-flash-agentic --repeats 3

- 영상은 프로필마다 한 번만 올리고(준비), 케이스 × 반복 횟수만큼 질의한다.
- 기록은 질의가 끝날 때마다 저장되므로 중간에 멈춰도 그때까지의 결과는 남는다.
- 실행이 끝나면 report.py와 같은 요약을 출력한다. 여러 실행 비교는 report.py로.
"""
import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import config
import report
from backends import get_backend, get_profile
from common import VideoSearchError
from testset import Case, load_testset

# 일시 오류(5xx, 분당 한도 429)를 다시 시도하기 전 대기 시간(초). 대기 시간은 질의 지연에 포함되지 않는다.
RETRY_DELAYS = (15, 45, 90)


def _retryable(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)  # google-genai / twelvelabs
    if code == 429:
        return "PerDay" not in str(e)  # 일일 할당량 소진은 기다려도 풀리지 않는다
    return isinstance(code, int) and code >= 500


def _short(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    return text if len(text) <= 200 else text[:200] + "…"


def query_with_retry(backend, client, handle, case: Case, profile: dict, max_matches: int, log_prefix: str):
    """(결과, 시도 횟수, 재시도한 오류 목록). 재시도로도 안 되면 마지막 예외에 attempts/retry_errors를 붙여 던진다."""
    retry_errors = []
    for attempt in range(1, len(RETRY_DELAYS) + 2):
        try:
            return backend.query(client, handle, case.query, profile, max_matches), attempt, retry_errors
        except Exception as e:
            if not _retryable(e) or attempt > len(RETRY_DELAYS):
                e.attempts, e.retry_errors = attempt, retry_errors
                raise
            retry_errors.append(_short(e))
            delay = RETRY_DELAYS[attempt - 1]
            print(f"{log_prefix}   일시 오류, {delay}s 후 재시도: {_short(e)}", file=sys.stderr)
            time.sleep(delay)


class PreparedVideos:
    """한 번의 evaluate 실행 안에서 프로필끼리 영상 업로드/인덱싱 결과를 공유한다.

    Gemini 업로드는 모델과 상관없으므로 같은 영상은 한 번만 올린다. TwelveLabs는 인덱스 모델별로 따로 준비한다.
    공유받은 프로필의 prepare 기록에는 처음 준비할 때의 시간을 그대로 남기고 shared를 붙인다.
    """

    def __init__(self):
        self._items = {}  # key -> (backend, client, handle, entry)

    def get(self, backend, client, video: str, profile: dict, log_prefix: str):
        key = (profile["backend"], video, None if profile["backend"] == "gemini" else profile["model"])
        if key in self._items:
            handle, entry = self._items[key][2:]
            # 이번 프로필에서는 새로 인덱싱하지 않았으므로 인덱싱 비용을 다시 세지 않게 reused로 표시
            return handle, {**entry, "shared": True, "info": {**entry.get("info", {}), "reused": True}}
        entry, handle = {"video": video}, None
        started = time.monotonic()
        try:
            handle, entry["info"] = backend.prepare(client, Path(video), profile)
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
            print(f"{log_prefix} 영상 준비 실패: {entry['error']}", file=sys.stderr)
        entry["seconds"] = time.monotonic() - started
        if handle is not None:
            self._items[key] = (backend, client, handle, entry)
        return handle, entry

    def cleanup(self) -> None:
        for backend, client, handle, _ in self._items.values():
            backend.cleanup(client, handle)
        self._items.clear()


def run_profile(name: str, profile: dict, testset_path: Path, meta: dict, cases: list[Case],
                repeats: int, max_matches: int, prepared: PreparedVideos) -> Path:
    backend = get_backend(profile["backend"])
    client = backend.make_client()
    runnable = [c for c in cases if not c.skip_reason]

    config.RESULTS_DIR.mkdir(exist_ok=True)
    started_at = datetime.now()
    out_path = config.RESULTS_DIR / f"{started_at:%Y%m%d-%H%M%S}_{name}.json"
    n = 2
    while out_path.exists():  # 같은 초에 시작한 실행이 덮어쓰지 않게
        out_path = config.RESULTS_DIR / f"{started_at:%Y%m%d-%H%M%S}-{n}_{name}.json"
        n += 1
    run = {
        "profile_name": name,
        "profile": profile,
        "testset": str(testset_path.resolve()),
        "youtube_url": meta["youtube_url"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "repeats": repeats,
        "max_matches": max_matches,
        "cases": [asdict(c) for c in cases],
        "prepare": [],   # 영상별 업로드/인덱싱 기록
        "records": [],   # 질의 1회당 1개
    }

    def save() -> None:
        out_path.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")

    handles = {}
    try:
        for video in dict.fromkeys(c.video for c in runnable):
            handle, entry = prepared.get(backend, client, video, profile, f"[{name}]")
            if handle is not None:
                handles[video] = handle
            run["prepare"].append(entry)
            save()

        # 반복을 바깥 루프로 둬서 같은 케이스의 반복 질의가 연달아 나가지 않게 한다.
        total, done = len(runnable) * repeats, 0
        for rep in range(repeats):
            for case in runnable:
                done += 1
                print(f"[{name}] ({done}/{total}) {case.id} #{rep + 1}: {case.query}", file=sys.stderr)
                record = {"case_id": case.id, "repeat": rep}
                started = time.monotonic()
                try:
                    if case.video not in handles:
                        raise RuntimeError("영상 준비 실패")
                    result, attempts, retry_errors = query_with_retry(
                        backend, client, handles[case.video], case, profile, max_matches, f"[{name}]")
                    record.update(status="ok", attempts=attempts, retry_errors=retry_errors, **asdict(result))
                except Exception as e:  # 한 질의 실패가 전체 평가를 멈추지 않게
                    record.update(status="error", error=f"{type(e).__name__}: {e}",
                                  attempts=getattr(e, "attempts", 1), retry_errors=getattr(e, "retry_errors", []),
                                  latency_sec=time.monotonic() - started)
                    print(f"[{name}]   오류: {_short(e)}", file=sys.stderr)
                run["records"].append(record)
                save()
    finally:  # 업로드 정리는 모든 프로필이 끝난 뒤 main에서
        run["finished_at"] = datetime.now().isoformat(timespec="seconds")
        save()
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="테스트셋을 프로필별로 실행해 평가 기록을 남긴다.")
    parser.add_argument("testset", type=Path, help="테스트셋 JSON 경로")
    parser.add_argument("--profile", action="append",
                        help=f"profiles.json의 프로필 이름. 여러 번 지정 가능 (기본: {config.DEFAULT_PROFILE})")
    parser.add_argument("--repeats", type=int, default=1, help="케이스별 반복 횟수. 출력 안정성을 보려면 3 이상 (기본: 1)")
    parser.add_argument("--max-matches", type=int, default=5, help="질의당 최대 후보 수 K (기본: 5)")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="이 케이스만 실행 (예: --cases c02 c03)")
    args = parser.parse_args()

    try:
        profiles = {name: get_profile(name) for name in args.profile or [config.DEFAULT_PROFILE]}
    except VideoSearchError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    meta, cases = load_testset(args.testset)
    if args.cases:
        unknown = set(args.cases) - {c.id for c in cases}
        if unknown:
            print(f"오류: 테스트셋에 없는 케이스: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        cases = [c for c in cases if c.id in args.cases]
    for case in cases:
        if case.skip_reason:
            print(f"[SKIP] {case.id}: {case.skip_reason}", file=sys.stderr)
    if all(c.skip_reason for c in cases):
        print("실행할 케이스가 없습니다.")
        return 0

    paths = []
    prepared = PreparedVideos()
    try:
        for name, profile in profiles.items():
            try:
                paths.append(run_profile(name, profile, args.testset, meta, cases,
                                         args.repeats, args.max_matches, prepared))
            except VideoSearchError as e:
                print(f"[{name}] 오류: {e}", file=sys.stderr)
    finally:
        prepared.cleanup()
    for path in paths:
        print(f"기록 저장: {path}")
    if paths:
        report.print_report([report.load_run(p) for p in paths])
    return 0


if __name__ == "__main__":
    sys.exit(main())
