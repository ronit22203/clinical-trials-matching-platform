#!/usr/bin/env python3
"""Download random samples from S3 bucket (one from biorxiv, one from medrxiv)."""

import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str]) -> str:
    """Run a shell command and return output."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_random_file(bucket: str, prefix: str, region: str) -> str:
    """Get a random paper.pdf file from the specified S3 prefix."""
    cmd = [
        "aws", "s3api", "list-objects-v2",
        "--bucket", bucket,
        "--prefix", prefix,
        "--query", "Contents[?contains(Key, 'paper.pdf')].Key",
        "--output", "text",
        "--region", region,
    ]
    output = run_command(cmd)
    if not output or output == "None":
        raise ValueError(f"No files found under s3://{bucket}/{prefix}")
    
    files = output.split()
    import random
    return random.choice(files)


def download_file(bucket: str, key: str, dest: Path, region: str) -> None:
    """Download a file from S3 to local destination."""
    cmd = [
        "aws", "s3", "cp",
        f"s3://{bucket}/{key}",
        str(dest),
        "--region", region,
    ]
    print(f"Downloading: {key} -> {dest}")
    run_command(cmd)


def main():
    bucket = os.environ.get("AWS_S3_BUCKET", os.environ.get("S3_BUCKET_NAME", ""))
    region = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
    if not bucket:
        print("Error: set AWS_S3_BUCKET or S3_BUCKET_NAME environment variable.", file=sys.stderr)
        sys.exit(1)
    output_dir = Path(__file__).parent.parent / "samples"
    output_dir.mkdir(exist_ok=True)
    
    try:
        # Get random biorxiv sample (from 2026/03/03)
        print("Fetching random biorxiv sample...")
        biorxiv_key = get_random_file(bucket, "raw/biorxiv/2026/03/03/", region)
        download_file(bucket, biorxiv_key, output_dir / "biorxiv_sample.pdf", region)
        
        # Get random medrxiv sample (from 2026/03/04)
        print("Fetching random medrxiv sample...")
        medrxiv_key = get_random_file(bucket, "raw/medrxiv/2026/03/04/", region)
        download_file(bucket, medrxiv_key, output_dir / "medrxiv_sample.pdf", region)
        
        print("\n✓ Downloaded 2 samples to:", output_dir)
    except subprocess.CalledProcessError as e:
        print(f"Error running AWS command: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
