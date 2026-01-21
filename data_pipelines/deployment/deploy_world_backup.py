"""
Prefect deployment script for Minecraft world backup flow

This script creates a Prefect deployment that runs the world backup pipeline
using the custom Docker image with all dependencies.

Usage:
    python deployment/deploy_world_backup.py
"""

import sys
from pathlib import Path

# Add parent directory to path to import flow
sys.path.append(str(Path(__file__).parent.parent))

from flow.world_backup.main import world_backup_pipeline


if __name__ == "__main__":
    # Deploy the flow using Prefect 3.0 API
    world_backup_pipeline.deploy(
        name="minecraft-world-backup",
        work_pool_name="kubernetes-pool",  # Update this to match your work pool name
        image="haziqishere/python-general:latest",
        build=False,  # Skip build - use pre-built image from CI/CD
        push=False,   # Skip push - image is already pushed by CI/CD
        tags=["minecraft", "backup", "s3"],
        description="Automated Minecraft world backup to S3 with compression",
        version="1.0.0",
        job_variables={
            "namespace": "minecraft",
            "service_account_name": "prefect-worker",
            "image_pull_policy": "Always",
            "finished_job_ttl": 300,  # Clean up completed jobs after 5 minutes
        },
    )

    print("✓ Deployment 'minecraft-world-backup' created successfully!")