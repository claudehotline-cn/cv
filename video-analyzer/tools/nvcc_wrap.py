#!/usr/bin/env python3
import os
import sys
import subprocess


def main():
    if len(sys.argv) < 2:
        print("nvcc_wrap.py: usage: nvcc_wrap.py <path-to-nvcc> [args...]", file=sys.stderr)
        return 2

    nvcc = sys.argv[1]
    args = sys.argv[2:]

    cmd = [nvcc] + args
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except FileNotFoundError:
        print(f"nvcc_wrap.py: nvcc not found: {nvcc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

