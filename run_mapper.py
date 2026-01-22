#!/usr/bin/env python3
"""
Convenience script to run the mapper from the project root.
This script uses uv to run the mapper with proper dependencies.
"""

import subprocess
import sys
import os

def main():
    """Run the mapper using uv from the mapper directory."""
    mapper_dir = os.path.join(os.path.dirname(__file__), 'mapper')

    if not os.path.exists(mapper_dir):
        print(f"❌ Mapper directory not found: {mapper_dir}")
        sys.exit(1)

    print("🚀 Starting Agentic QA Discovery Mapper...")

    # Change to mapper directory and run with uv
    try:
        result = subprocess.run(
            ['uv', 'run', 'python', 'discovery_mapper.py'],
            cwd=mapper_dir,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Mapper failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("❌ uv command not found. Please install uv: https://github.com/astral-sh/uv")
        print("   Or run the mapper directly from the mapper/ directory")
        sys.exit(1)

if __name__ == "__main__":
    main()