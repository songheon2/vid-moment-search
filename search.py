"""단일 영상 + 쿼리로 장면 타임코드를 찾는 CLI.

    python search.py <영상 경로> "<찾을 장면 묘사>" [--profile 이름] [--max-matches N]
"""
import argparse
import sys
from pathlib import Path

import config
from backends import get_backend, get_profile
from common import VideoSearchError, format_timecode


def main() -> int:
    parser = argparse.ArgumentParser(description="자연어 쿼리로 영상 속 장면의 타임코드를 찾는다.")
    parser.add_argument("video", type=Path, help="로컬 영상 파일 경로")
    parser.add_argument("query", help="찾을 장면 묘사")
    parser.add_argument("--profile", default=config.DEFAULT_PROFILE,
                        help=f"profiles.json의 프로필 이름 (기본: {config.DEFAULT_PROFILE})")
    parser.add_argument("--max-matches", type=int, default=5, help="최대 후보 수 (기본: 5)")
    args = parser.parse_args()

    try:
        profile = get_profile(args.profile)
        backend = get_backend(profile["backend"])
        client = backend.make_client()
        handle, _ = backend.prepare(client, args.video, profile)
        try:
            result = backend.query(client, handle, args.query, profile, args.max_matches)
        finally:
            backend.cleanup(client, handle)
    except VideoSearchError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    print(f"\n프로필: {args.profile} ({profile['model']})")
    print(f"쿼리: {args.query}")
    print(f"응답 시간: {result.latency_sec:.1f}s")
    if result.format_issues:
        print(f"형식 문제: {'; '.join(result.format_issues)}")
    print()
    if not result.moments:
        print("일치하는 장면을 찾지 못했습니다.")
        return 0
    for rank, m in enumerate(result.moments, 1):
        line = f"{rank}. {format_timecode(m.start_sec)} ~ {format_timecode(m.end_sec)}"
        if m.confidence:
            line += f"  [{m.confidence}]"
        if m.reason:
            line += f"  {m.reason}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
