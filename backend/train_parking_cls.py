"""Train YOLOv8 classification model for parking occupancy (empty vs occupied)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train YOLOv8 classifier for parking occupancy"
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Dataset root with train/ and val/ class folders",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n-cls.pt",
        help="Base classification model",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--project", type=Path, default=Path("runs") / "parking_cls")
    parser.add_argument("--name", type=str, default="yolov8_parking_cls")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.data.exists():
        raise FileNotFoundError(f"Dataset not found: {args.data}")

    model = YOLO(args.model)
    result = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(args.project),
        name=args.name,
        workers=args.workers,
    )

    best = Path(result.save_dir) / "weights" / "best.pt"
    val_model = YOLO(str(best) if best.exists() else args.model)
    metrics = val_model.val(data=str(args.data), imgsz=args.imgsz, device=args.device)

    print("Training finished")
    print(f"Run folder: {result.save_dir}")
    print(f"Best model: {best if best.exists() else 'not found'}")
    print(f"Top1 accuracy: {getattr(metrics, 'top1', 'n/a')}")
    print(f"Top5 accuracy: {getattr(metrics, 'top5', 'n/a')}")


if __name__ == "__main__":
    main()
