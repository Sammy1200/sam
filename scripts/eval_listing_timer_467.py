from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import vision


@dataclass
class TimerSample:
    path: Path
    standard_answer: str
    expected_hour_result: str | None
    roi_already_cropped: bool


def _normalize_stem(stem: str) -> str:
    normalized = stem.replace("_roi", "").replace("_full", "")
    normalized = normalized.replace("：", ":").replace(".", ":")
    return normalized


def _parse_expected_hour_result(standard_answer: str) -> str | None:
    parts = standard_answer.split(":")
    if not parts:
        return None
    hour = parts[0]
    if hour in {"46", "47"}:
        return hour
    return None


def load_samples(sample_dir: Path) -> list[TimerSample]:
    samples = []
    for path in sorted(sample_dir.glob("*.png")):
        standard_answer = _normalize_stem(path.stem)
        samples.append(
            TimerSample(
                path=path,
                standard_answer=standard_answer,
                expected_hour_result=_parse_expected_hour_result(standard_answer),
                roi_already_cropped=path.stem.endswith("_roi"),
            )
        )
    return samples


def read_image(path: Path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)


def evaluate_samples(samples: list[TimerSample]):
    rows = []
    for sample in samples:
        image = read_image(sample.path)
        result = None
        if image is not None:
            result = vision.recognize_listing_timer_hour_value(
                image,
                roi_already_cropped=sample.roi_already_cropped,
            )
        rows.append(
            {
                "file": sample.path.name,
                "standard_answer": sample.standard_answer,
                "result": result,
                "correct": result == sample.expected_hour_result,
            }
        )
    return rows


def summarize_rows(rows):
    total = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    return {
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
    }


def print_rows(rows):
    for row in rows:
        print(
            json.dumps(
                {
                    "file": row["file"],
                    "standard_answer": row["standard_answer"],
                    "result": row["result"],
                    "correct": row["correct"],
                },
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser(description="批量评测上架倒计时小时位 46/47 识别。")
    parser.add_argument(
        "--samples",
        default=str(REPO_ROOT / "samples" / "ceshimuban1"),
        help="真实样本目录。",
    )
    args = parser.parse_args()

    samples = load_samples(Path(args.samples))
    print(json.dumps({"sample_count": len(samples)}, ensure_ascii=False))
    rows = evaluate_samples(samples)
    print_rows(rows)
    print(json.dumps({"summary": summarize_rows(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
