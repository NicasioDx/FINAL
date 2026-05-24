import argparse
import json
from pathlib import Path

import cv2


def parse_args():
    parser = argparse.ArgumentParser(description="Create a small YOLO dataset for demo parking-slot finetuning.")
    parser.add_argument("--video", default="videos/demo_parking.mp4")
    parser.add_argument("--rois", default="manual_rois.json")
    parser.add_argument("--output", default="demo_slot_dataset")
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--stride", type=int, default=30)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    return parser.parse_args()


def load_rois(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    source_size = data.get("image_size", [960, 540])
    rois = data.get("rois", data if isinstance(data, list) else [])
    return source_size, rois


def yolo_line(roi, source_size, target_width, target_height):
    source_width, source_height = source_size
    sx = target_width / source_width
    sy = target_height / source_height

    if "points" in roi:
        xs = [float(point[0]) for point in roi["points"]]
        ys = [float(point[1]) for point in roi["points"]]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    else:
        x1, y1, x2, y2 = roi["x1"], roi["y1"], roi["x2"], roi["y2"]

    x1 = max(0, min(target_width - 1, x1 * sx))
    y1 = max(0, min(target_height - 1, y1 * sy))
    x2 = max(0, min(target_width - 1, x2 * sx))
    y2 = max(0, min(target_height - 1, y2 * sy))

    cx = ((x1 + x2) / 2) / target_width
    cy = ((y1 + y2) / 2) / target_height
    width = (x2 - x1) / target_width
    height = (y2 - y1) / target_height
    return f"0 {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"


def main():
    args = parse_args()
    base = Path(args.output)
    for split in ("train", "val"):
        (base / "images" / split).mkdir(parents=True, exist_ok=True)
        (base / "labels" / split).mkdir(parents=True, exist_ok=True)

    source_size, rois = load_rois(Path(args.rois))
    labels = [yolo_line(roi, source_size, args.width, args.height) for roi in rois]

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {args.video}")

    saved = 0
    frame_index = 0
    while saved < args.frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            break

        split = "val" if saved % 6 == 0 else "train"
        resized = cv2.resize(frame, (args.width, args.height))
        stem = f"demo_{saved:04d}"
        cv2.imwrite(str(base / "images" / split / f"{stem}.jpg"), resized)
        (base / "labels" / split / f"{stem}.txt").write_text("\n".join(labels) + "\n", encoding="utf-8")

        saved += 1
        frame_index += args.stride

    cap.release()

    data_yaml = (
        f"path: {base.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: parking_slot\n"
    )
    (base / "data.yaml").write_text(data_yaml, encoding="utf-8")
    print(f"Saved {saved} images with {len(rois)} parking-slot labels each to {base}")


if __name__ == "__main__":
    main()
