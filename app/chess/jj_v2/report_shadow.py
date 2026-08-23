"""CLI: 汇总一个 JJ v2 影子识别会话。"""

import argparse
import json

from .shadow_report import build_shadow_report


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总新版 JJ 影子识别结果")
    parser.add_argument("session_dir")
    args = parser.parse_args()
    print(json.dumps(build_shadow_report(args.session_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
