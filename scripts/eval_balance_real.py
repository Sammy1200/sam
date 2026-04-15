from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import vision


SAMPLE_NAME_RE = re.compile(r"^(?P<answer>.+?)_(?P<index>\d+)_(?P<kind>roi|full)\.png$", re.IGNORECASE)


@dataclass
class BalanceSample:
    answer: str
    category: str
    path: Path
    source_kind: str


def _strip_unit(answer: str) -> str:
    return re.sub(r"[万亿]$", "", answer)


def _categorize_answer(answer: str) -> str:
    if answer.endswith("亿") and "." in answer:
        return "小数亿"
    if answer.endswith("万") and "." in answer:
        return "小数万"
    if answer.endswith(("亿", "万")):
        return "整数单位"
    if "." in answer:
        return "无单位小数"
    return "纯数字"


def load_balance_samples(sample_dir: Path) -> list[BalanceSample]:
    grouped = {}
    for path in sorted(sample_dir.glob("*.png")):
        match = SAMPLE_NAME_RE.match(path.name)
        if not match:
            continue
        answer = match.group("answer")
        index = match.group("index")
        kind = match.group("kind").lower()
        key = (_strip_unit(answer), index)
        entry = grouped.setdefault(key, {"answers": set(), "files": {}})
        entry["answers"].add(answer)
        entry["files"][kind] = path

    samples: list[BalanceSample] = []
    for _, entry in sorted(grouped.items()):
        answers = sorted(entry["answers"], key=lambda value: (value.endswith(("万", "亿")), len(value)), reverse=True)
        answer = answers[0]
        path = entry["files"].get("roi") or entry["files"].get("full")
        kind = "roi" if "roi" in entry["files"] else "full"
        if path is None:
            continue
        samples.append(
            BalanceSample(
                answer=answer,
                category=_categorize_answer(answer),
                path=path,
                source_kind=kind,
            )
        )
    return samples


def read_image(path: Path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)


def recognize_sample(sample: BalanceSample, params=None) -> str | None:
    image = read_image(sample.path)
    if image is None:
        return None
    if sample.source_kind == "full":
        return vision.recognize_balance_image(image, roi_already_cropped=False, params=params)
    return vision.recognize_balance_image(image, roi_already_cropped=True, params=params)


def evaluate_samples(samples: list[BalanceSample], params=None):
    rows = []
    for sample in samples:
        result = recognize_sample(sample, params=params)
        rows.append(
            {
                "answer": sample.answer,
                "category": sample.category,
                "correct": result == sample.answer,
                "file": sample.path.name,
                "result": result,
                "source_kind": sample.source_kind,
            }
        )
    return rows


def summarize_results(rows):
    total = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    by_category = {}
    for row in rows:
        stats = by_category.setdefault(row["category"], {"correct": 0, "total": 0})
        stats["total"] += 1
        if row["correct"]:
            stats["correct"] += 1
    return {
        "accuracy": (correct / total) if total else 0.0,
        "by_category": by_category,
        "correct": correct,
        "total": total,
    }


def rank_results(rows):
    summary = summarize_results(rows)
    category_stats = summary["by_category"]
    decimal_yi = category_stats.get("小数亿", {}).get("correct", 0)
    decimal_wan = category_stats.get("小数万", {}).get("correct", 0)
    integer_unit = category_stats.get("整数单位", {}).get("correct", 0)
    wrong_none = sum(1 for row in rows if not row["correct"] and row["result"] is None)
    wrong_text = sum(1 for row in rows if not row["correct"] and row["result"] is not None)
    return (
        summary["correct"],
        wrong_none,
        decimal_yi,
        decimal_wan,
        integer_unit,
        -wrong_text,
    )


def search_best_params(samples: list[BalanceSample]):
    defaults = vision._get_balance_params()

    stage_one_grid = {
        "binary_blur_size": [0, 3, 5],
        "min_component_area": [4, 6, 8],
        "segment_close_kernel_size": [1, 2],
        "segment_merge_gap": [1, 2, 3],
        "segment_max_group_size": [2, 3],
    }

    best_stage_one = None
    for values in itertools.product(*stage_one_grid.values()):
        params = defaults.copy()
        params.update(dict(zip(stage_one_grid.keys(), values)))
        rows = evaluate_samples(samples, params=params)
        candidate = (rank_results(rows), params, rows)
        if best_stage_one is None or candidate[0] > best_stage_one[0]:
            best_stage_one = candidate

    stage_two_grid = {
        "digit_threshold": [0.40, 0.45, 0.50],
        "dot_threshold": [0.20, 0.25, 0.30],
        "unit_threshold": [0.40, 0.45, 0.50],
        "dot_max_width": [6, 8],
        "dot_max_height": [6, 8],
        "dot_max_area": [10, 18],
        "dot_baseline_offset_ratio": [0.25, 0.35, 0.45],
        "dot_max_neighbor_gap": [4, 6],
        "unit_min_width": [10, 12, 14],
    }

    best_stage_two = None
    base_params = best_stage_one[1]
    for values in itertools.product(*stage_two_grid.values()):
        params = base_params.copy()
        params.update(dict(zip(stage_two_grid.keys(), values)))
        rows = evaluate_samples(samples, params=params)
        candidate = (rank_results(rows), params, rows)
        if best_stage_two is None or candidate[0] > best_stage_two[0]:
            best_stage_two = candidate

    return best_stage_two[1], best_stage_two[2]


def print_rows(rows):
    for row in rows:
        print(
            json.dumps(
                {
                    "file": row["file"],
                    "answer": row["answer"],
                    "result": row["result"],
                    "correct": row["correct"],
                },
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser(description="基于真实截图样本批量评测余额模板匹配。")
    parser.add_argument(
        "--samples",
        default=str(Path(__file__).resolve().parents[1] / "samples" / "balance_real"),
        help="真实余额样本目录",
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="执行批量扫参并输出最优参数",
    )
    args = parser.parse_args()

    sample_dir = Path(args.samples)
    samples = load_balance_samples(sample_dir)
    print(json.dumps({"sample_count": len(samples)}, ensure_ascii=False))

    if args.search:
        best_params, best_rows = search_best_params(samples)
        print(json.dumps({"best_params": best_params}, ensure_ascii=False, sort_keys=True))
        print_rows(best_rows)
        print(json.dumps({"summary": summarize_results(best_rows)}, ensure_ascii=False))
        return

    rows = evaluate_samples(samples)
    print_rows(rows)
    print(json.dumps({"summary": summarize_results(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
