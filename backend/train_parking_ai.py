"""Train YOLOv8 model for parking-space detection.

Expected dataset layout (YOLO format):
dataset_root/
  images/
    train/*.jpg
    val/*.jpg
  labels/
    train/*.txt
    val/*.txt
  parking_slots.yaml

Each label .txt line:
  class_id x_center y_center width height
All coordinates are normalized to 0..1.
"""

from __future__ import annotations

import argparse
import functools
import os
from pathlib import Path

# PyTorch 2.6 changed torch.load default to weights_only=True.
# Ultralytics checkpoints like yolov8n.pt require full object loading.
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

# Reduce CUDA memory fragmentation on Windows WDDM drivers.
# Must be set unconditionally before any CUDA allocation.
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import torch

torch.load = functools.partial(torch.load, weights_only=False)

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train YOLOv8 for parking-space detection"
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to dataset yaml, for example: ../datasets/parking_slots.yaml",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="Base model checkpoint (pt) or yaml model config",
    )
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=1280, help="Image size")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="auto, cpu, GPU id, or comma-separated GPU ids",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("runs") / "parking",
        help="Output directory for training runs",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="yolov8_parking",
        help="Run name under project directory",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=30,
        help="Early stopping patience",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Dataloader workers",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Cache images in RAM for faster training",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the latest run with the same project/name",
    )
    parser.add_argument(
        "--mosaic",
        type=float,
        default=0.0,
        help="Mosaic augmentation probability (set 0 to disable and reduce RAM usage)",
    )
    parser.add_argument(
        "--close-mosaic",
        type=int,
        default=0,
        help="Disable mosaic in the last N epochs (0 keeps current setting)",
    )
    return parser.parse_args()


def validate_inputs(data_yaml: Path, model_path: str) -> None:
    if not data_yaml.exists():
        raise FileNotFoundError(f"Dataset yaml not found: {data_yaml}")

    # Model can be either a local path or an alias (yolov8n.pt).
    model_file = Path(model_path)
    if model_file.suffix in {".pt", ".yaml", ".yml"} and model_file.exists() is False:
        if model_path not in {
            "yolov8n.pt",
            "yolov8s.pt",
            "yolov8m.pt",
            "yolov8l.pt",
            "yolov8x.pt",
        }:
            raise FileNotFoundError(f"Model file not found: {model_path}")


def main() -> None:
    args = parse_args()
    validate_inputs(args.data, args.model)

    # Use CPU automatically when CUDA is not available.
    resolved_device = args.device
    if args.device == "auto":
        resolved_device = "0" if torch.cuda.is_available() else "cpu"

    # Release any leftover CUDA allocations from previous processes.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    model = YOLO(args.model)

    train_result = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=resolved_device,
        project=str(args.project),
        name=args.name,
        patience=args.patience,
        workers=args.workers,
        cache=args.cache,
        resume=args.resume,
        pretrained=True,
        close_mosaic=args.close_mosaic,
        mosaic=args.mosaic,
    )

    # Validate best checkpoint after training.
    best_ckpt = Path(train_result.save_dir) / "weights" / "best.pt"
    val_target = str(best_ckpt) if best_ckpt.exists() else args.model
    model = YOLO(val_target)
    metrics = model.val(data=str(args.data), imgsz=args.imgsz, device=resolved_device)

    print("Training finished")
    print(f"Run folder: {train_result.save_dir}")
    print(f"Best model: {best_ckpt if best_ckpt.exists() else 'not found'}")
    print(f"Validation mAP50: {getattr(metrics.box, 'map50', 'n/a')}")
    print(f"Validation mAP50-95: {getattr(metrics.box, 'map', 'n/a')}")


if __name__ == "__main__":
    main()
