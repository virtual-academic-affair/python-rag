"""Generate Python gRPC stubs from proto files.

Usage:
    python scripts/gen_proto.py
"""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    proto_root = root / "app" / "proto"
    proto_dir = proto_root / "label"
    proto_file = proto_root / "label.proto"

    if not proto_file.exists():
        print(f"Proto file not found: {proto_file}")
        return 1

    proto_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_root}",
        f"--python_out={proto_dir}",
        f"--grpc_python_out={proto_dir}",
        str(proto_file),
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(root), check=False)
    if result.returncode != 0:
        print("Failed generating protobuf/gRPC stubs")
        return result.returncode

    print("Generated stubs in app/proto/label/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

