"""Entry point script to run the application"""
from pathlib import Path
import subprocess
import sys

import uvicorn

from app.core.config import settings


PROTO_STUBS = (
    Path(__file__).resolve().parent
    / "app"
    / "proto"
    / "class_registration"
    / "class_registration_pb2.py",
    Path(__file__).resolve().parent
    / "app"
    / "proto"
    / "class_registration"
    / "class_registration_pb2_grpc.py",
    Path(__file__).resolve().parent / "app" / "proto" / "inquiry" / "inquiry_pb2.py",
    Path(__file__).resolve().parent / "app" / "proto" / "inquiry" / "inquiry_pb2_grpc.py",
)


def ensure_grpc_stubs() -> None:
    if all(path.exists() for path in PROTO_STUBS):
        return

    print("gRPC stubs not found. Generating from proto...")
    result = subprocess.run(
        [sys.executable, "scripts/gen_proto.py"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to generate gRPC stubs. Run scripts/gen_proto.py")


if __name__ == "__main__":
    ensure_grpc_stubs()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL,
    )

