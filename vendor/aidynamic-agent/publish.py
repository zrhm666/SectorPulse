#!/usr/bin/env python3
"""
自动打包并发布到私有 PyPI 服务器
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """运行命令并实时输出"""
    print(f"🔧 执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent, check=False)
    if check and result.returncode != 0:
        print(f"❌ 命令失败，退出码: {result.returncode}")
        sys.exit(result.returncode)
    return result


def build_package() -> list[Path]:
    """打包项目"""
    print("\n📦 开始打包...")

    # 清理旧的 dist 目录
    dist_dir = Path(__file__).parent / "dist"
    if dist_dir.exists():
        import shutil

        shutil.rmtree(dist_dir)
        print("🧹 已清理旧的 dist 目录")

    # 使用 uv build 打包
    run_command(["uv", "build"])

    # 列出生成的文件
    dist_files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    print("\n✅ 打包完成，生成文件:")
    for f in dist_files:
        print(f"   - {f.name}")

    return dist_files


def publish_package(
    repository_url: str,
    username: str = "",
    password: str = "",
) -> None:
    """发布到 PyPI 服务器"""
    print(f"\n🚀 开始发布到 {repository_url}...")

    dist_dir = Path(__file__).parent / "dist"
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))

    cmd = [
        "twine",
        "upload",
        "--repository-url",
        repository_url,
        "--username",
        username,
        "--password",
        password,
        *[str(f) for f in files],
    ]

    run_command(cmd)

    print("\n✅ 发布成功!")
    print(f"📍 包地址: {repository_url.rstrip('/')}/aidynamic-agent/")


def main():
    parser = argparse.ArgumentParser(description="打包并发布 aidynamic-agent 包到私有 PyPI 服务器")
    parser.add_argument(
        "--url",
        default="http://192.168.1.15:8080/",
        help="PyPI 服务器 URL (默认: http://192.168.1.15:8080/)",
    )
    parser.add_argument(
        "--username",
        "-u",
        default="",
        help="PyPI 用户名 (默认为空)",
    )
    parser.add_argument(
        "--password",
        "-p",
        default="",
        help="PyPI 密码 (默认为空)",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="仅打包，不发布",
    )
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help="仅发布，不重新打包",
    )

    args = parser.parse_args()

    if not args.publish_only:
        build_package()

    if not args.build_only:
        publish_package(
            repository_url=args.url,
            username=args.username,
            password=args.password,
        )


if __name__ == "__main__":
    main()
