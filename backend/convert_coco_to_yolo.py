"""Convert COCO detection annotations to YOLO format for Ultralytics training.

Expected extracted dataset structure:
dataset_root/
  train/
    _annotations.coco.json
    *.jpg
  valid/
    _annotations.coco.json
    *.jpg
  test/
    _annotations.coco.json
    *.jpg
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert COCO json to YOLO txt labels")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Path to extracted dataset root containing train/valid/test",
    )
    parser.add_argument(
        "--train-dir",
        type=str,
        default="train",
        help="Training split folder name",
    )
    parser.add_argument(
        "--val-dir",
        type=str,
        default="valid",
        help="Validation split folder name",
    )
    parser.add_argument(
        "--test-dir",
        type=str,
        default="test",
        help="Test split folder name",
    )
    parser.add_argument(
        "--yaml-name",
        type=str,
        default="parking_slots.yaml",
        help="Output dataset yaml filename",
    )
    return parser.parse_args()


def coco_box_to_yolo(box: list[float], width: int, height: int) -> tuple[float, float, float, float]:
    x, y, w, h = box
    x_center = (x + (w / 2.0)) / width
    y_center = (y + (h / 2.0)) / height
    return x_center, y_center, w / width, h / height


def convert_split(split_dir: Path) -> tuple[dict[int, str], int]:
    ann_file = split_dir / "_annotations.coco.json"
    if not ann_file.exists():
        return {}, 0

    with ann_file.open("r", encoding="utf-8") as f:
        coco = json.load(f)

    categories = coco.get("categories", [])
    category_map = {cat["id"]: cat["name"] for cat in categories}
    category_ids_sorted = sorted(category_map.keys())
    cat_to_idx = {cat_id: idx for idx, cat_id in enumerate(category_ids_sorted)}

    image_map = {}
    for img in coco.get("images", []):
        image_map[img["id"]] = {
            "file_name": img["file_name"],
            "width": img["width"],
            "height": img["height"],
        }

    labels_by_image: dict[int, list[str]] = defaultdict(list)
    for ann in coco.get("annotations", []):
        img_id = ann["image_id"]
        cat_id = ann["category_id"]
        if img_id not in image_map or cat_id not in cat_to_idx:
            continue

        img_info = image_map[img_id]
        x_c, y_c, w, h = coco_box_to_yolo(
            ann["bbox"],
            width=img_info["width"],
            height=img_info["height"],
        )
        yolo_cls = cat_to_idx[cat_id]
        labels_by_image[img_id].append(
            f"{yolo_cls} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}"
        )

    written = 0
    for img_id, img_info in image_map.items():
        label_path = split_dir / f"{Path(img_info['file_name']).stem}.txt"
        lines = labels_by_image.get(img_id, [])
        label_path.write_text("\n".join(lines), encoding="utf-8")
        written += 1

    idx_to_name = {idx: category_map[cat_id] for cat_id, idx in cat_to_idx.items()}
    return idx_to_name, written


def write_dataset_yaml(
    dataset_root: Path,
    yaml_name: str,
    train_dir: str,
    val_dir: str,
    test_dir: str,
    names: dict[int, str],
) -> Path:
    yaml_path = dataset_root / yaml_name
    lines = [
        f"path: {dataset_root.resolve().as_posix()}",
        f"train: {train_dir}",
        f"val: {val_dir}",
    ]

    test_path = dataset_root / test_dir
    if test_path.exists():
        lines.append(f"test: {test_dir}")

    lines.append("names:")
    for idx in sorted(names.keys()):
        lines.append(f"  {idx}: {names[idx]}")

    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def main() -> None:
    args = parse_args()
    root = args.dataset_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Dataset root not found: {root}")

    split_names = [args.train_dir, args.val_dir, args.test_dir]
    all_names: dict[int, str] = {}
    total_labels_written = 0

    for split in split_names:
        split_path = root / split
        if not split_path.exists():
            continue
        names, count = convert_split(split_path)
        if names:
            all_names = names
        total_labels_written += count

    if not all_names:
        raise RuntimeError(
            "No COCO categories found. Check _annotations.coco.json in dataset splits."
        )

    yaml_path = write_dataset_yaml(
        dataset_root=root,
        yaml_name=args.yaml_name,
        train_dir=args.train_dir,
        val_dir=args.val_dir,
        test_dir=args.test_dir,
        names=all_names,
    )

    print("COCO -> YOLO conversion complete")
    print(f"Dataset root: {root}")
    print(f"Labels written for images: {total_labels_written}")
    print(f"Dataset yaml: {yaml_path}")
    print(f"Classes: {all_names}")


if __name__ == "__main__":
    main()
