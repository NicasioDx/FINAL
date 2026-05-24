"""Prepare PKLot + CNRPark style datasets for YOLO classification training.

This script scans input folders recursively, infers class labels from path/file names,
and creates a unified dataset in Ultralytics classification format:

output_dir/
  train/
    empty/
    occupied/
  val/
    empty/
    occupied/
"""

from __future__ import annotations

import argparse
import random
import shutil
from collections import defaultdict
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
EMPTY_KEYWORDS = ("empty", "free", "vacant", "no_car")
OCCUPIED_KEYWORDS = ("occupied", "full", "busy", "car", "nonempty", "not_empty")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge PKLot/CNRPark into train/val classification dataset"
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        required=True,
        help="One or more source dataset roots (PKLot/CNRPark folders)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("..") / "dataset" / "parking_cls",
        help="Output dataset folder",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.2,
        help="Validation ratio (0.0 - 0.5 recommended)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of hardlink (slower, larger disk usage)",
    )
    return parser.parse_args()


def infer_label(image_path: Path) -> str | None:
    text = str(image_path).lower().replace("-", "_")
    if any(key in text for key in EMPTY_KEYWORDS):
        return "empty"
    if any(key in text for key in OCCUPIED_KEYWORDS):
        return "occupied"
    return None


def find_images(root: Path) -> list[Path]:
    images: list[Path] = []
    for file_path in root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(file_path)
    return images


def reset_output(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    for split in ("train", "val"):
        (output_dir / split / "empty").mkdir(parents=True, exist_ok=True)
        (output_dir / split / "occupied").mkdir(parents=True, exist_ok=True)


def place_file(src: Path, dst: Path, use_copy: bool) -> None:
    if use_copy:
        shutil.copy2(src, dst)
        return
    try:
        dst.hardlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    source_roots = [Path(p).expanduser().resolve() for p in args.sources]
    for src in source_roots:
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")

    reset_output(args.output)

    grouped: dict[str, list[Path]] = defaultdict(list)
    unlabeled_count = 0

    for source in source_roots:
        for image_path in find_images(source):
            label = infer_label(image_path)
            if label is None:
                unlabeled_count += 1
                continue
            grouped[label].append(image_path)

    for label in ("empty", "occupied"):
        random.shuffle(grouped[label])

    summary = {}
    for label in ("empty", "occupied"):
        items = grouped[label]
        split_idx = int(len(items) * (1 - args.val_ratio))
        train_items = items[:split_idx]
        val_items = items[split_idx:]

        for split_name, split_items in (("train", train_items), ("val", val_items)):
            for idx, src in enumerate(split_items):
                dst_name = f"{label}_{idx:07d}{src.suffix.lower()}"
                dst_path = args.output / split_name / label / dst_name
                place_file(src, dst_path, use_copy=args.copy)

        summary[label] = {"train": len(train_items), "val": len(val_items)}

    print("Dataset prepared")
    print(f"Output: {args.output.resolve()}")
    print(f"Empty   -> train: {summary['empty']['train']}, val: {summary['empty']['val']}")
    print(
        f"Occupied-> train: {summary['occupied']['train']}, val: {summary['occupied']['val']}"
    )
    print(f"Skipped unlabeled images: {unlabeled_count}")


if __name__ == "__main__":
    main()
