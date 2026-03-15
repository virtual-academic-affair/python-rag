"""Generate Python gRPC stubs from proto files.

Usage:
    python scripts/gen_proto.py
"""

from pathlib import Path
import subprocess
import sys


def _fix_relative_imports(proto_dir: Path, module_name: str) -> None:
    grpc_file = proto_dir / f"{module_name}_pb2_grpc.py"
    pb2_file = proto_dir / f"{module_name}_pb2.py"

    for target_file, import_targets in (
        (grpc_file, [f"import {module_name}_pb2 as", "import common_pb2 as"]),
        (pb2_file, ["import common_pb2 as"]),
    ):
        if not target_file.exists():
            continue

        content = target_file.read_text(encoding="utf-8")
        if not any(needle in content for needle in import_targets):
            continue

        content = content.replace(
            f"import {module_name}_pb2 as",
            f"from . import {module_name}_pb2 as",
        )
        content = content.replace(
            "import common_pb2 as",
            "from . import common_pb2 as",
        )
        target_file.write_text(content, encoding="utf-8")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    proto_root = root / "app" / "proto"
    proto_targets = {
        "label": "label.proto",
        "class_registration": "class_registration.proto",
        "auth": "auth.proto",
        "task": "task.proto",
    }

    for target_dir, proto_name in proto_targets.items():
        proto_dir = proto_root / target_dir
        proto_file = proto_root / proto_name
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
            print("Failed generating protobuf/gRPC stubs for", proto_name)
            return result.returncode

        module_name = proto_file.stem
        _fix_relative_imports(proto_dir, module_name)

        common_proto = proto_root / "common.proto"
        if common_proto.exists():
            common_cmd = [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{proto_root}",
                f"--python_out={proto_dir}",
                str(common_proto),
            ]
            print("Running:", " ".join(common_cmd))
            common_result = subprocess.run(common_cmd, cwd=str(root), check=False)
            if common_result.returncode != 0:
                print("Failed generating protobuf stubs for common.proto")
                return common_result.returncode
            _fix_relative_imports(proto_dir, "common")

    print("Generated stubs in app/proto/<service>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

