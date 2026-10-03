"""단일 영상 + 쿼리로 장면 타임코드를 찾는 CLI.

    python search.py <영상 경로> "<찾을 장면 묘사>" [--backend gemini|twelvelabs] [--model MODEL] [--max-matches N]
"""
import argparse
import sys
from pathlib import Path

from backends import NAMES, get_backend
from common import VideoSearchError, format_timecode


def main() -> int:
    parser = argparse.ArgumentParser(description="자연어 쿼리로 영상 속 장면의 타임코드를 찾는다.")
    parser.add_argument("video", type=Path, help="로컬 영상 파일 경로")
    parser.add_argument("query", help="찾을 장면 묘사")
    parser.add_argument("--backend", choices=NAMES, default="gemini", help="검색 백엔드 (기본: gemini)")
    parser.add_argument("--model", help="모델 ID (기본: 백엔드별 config 값)")
    parser.add_argument("--max-matches", type=int, default=5, help="최대 후보 수 (기본: 5)")
    args = parser.parse_args()

    backend = get_backend(args.backend)
    model = args.model or backend.DEFAULT_MODEL
    try:
        client = backend.make_client()
        moments = backend.search_moments(client, args.video, args.query, model, args.max_matches)
    except VideoSearchError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    print(f"\n백엔드: {args.backend} / 모델: {model}")
    print(f"쿼리: {args.query}\n")
    if not moments:
        print("일치하는 장면을 찾지 못했습니다.")
        return 0
    for rank, m in enumerate(moments, 1):
        line = f"{rank}. {format_timecode(m.start_sec)} ~ {format_timecode(m.end_sec)}"
        if m.confidence:
            line += f"  [{m.confidence}]"
        if m.reason:
            line += f"  {m.reason}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
