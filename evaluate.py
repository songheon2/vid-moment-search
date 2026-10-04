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


def run_profile(name: str, profile: dict, testset_path: Path, meta: dict, cases: list[Case],
                repeats: int, max_matches: int) -> Path:
    backend = get_backend(profile["backend"])
    client = backend.make_client()
    runnable = [c for c in cases if not c.skip_reason]

    config.RESULTS_DIR.mkdir(exist_ok=True)
    started_at = datetime.now()
    out_path = config.RESULTS_DIR / f"{started_at:%Y%m%d-%H%M%S}_{name}.json"
    run = {
        "profile_name": name,
        "profile": profile,
        "testset": str(testset_path),
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
            entry = {"video": video}
            started = time.monotonic()
            try:
                handles[video], entry["info"] = backend.prepare(client, Path(video), profile)
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                print(f"[{name}] 영상 준비 실패: {entry['error']}", file=sys.stderr)
            entry["seconds"] = time.monotonic() - started
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
    finally:
        for handle in handles.values():
            backend.cleanup(client, handle)
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
    args = parser.parse_args()

    try:
        profiles = {name: get_profile(name) for name in args.profile or [config.DEFAULT_PROFILE]}
    except VideoSearchError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    meta, cases = load_testset(args.testset)
    for case in cases:
        if case.skip_reason:
            print(f"[SKIP] {case.id}: {case.skip_reason}", file=sys.stderr)
    if all(c.skip_reason for c in cases):
        print("실행할 케이스가 없습니다.")
        return 0

    paths = []
    for name, profile in profiles.items():
        try:
            paths.append(run_profile(name, profile, args.testset, meta, cases, args.repeats, args.max_matches))
        except VideoSearchError as e:
            print(f"[{name}] 오류: {e}", file=sys.stderr)
    for path in paths:
        print(f"기록 저장: {path}")
    if paths:
        report.print_report([report.load_run(p) for p in paths])
    return 0


if __name__ == "__main__":
    sys.exit(main())
