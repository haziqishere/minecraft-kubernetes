import os
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from prefect import task, flow, get_run_logger
from kubernetes import client, config

from utilities.aws_utils import (
    get_s3_client,
    get_sm_client,
    retrieve_secret,
    retrieve_credentials
)
from utilities.config_utils import get_json_config


@task
def get_minecraft_pod(namespace: str, label_selector: str):
    """Find the Minecraft pod using label selector"""
    logger = get_run_logger()

    # Load kubernetes config from in-cluster or kubeconfig
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except:
        config.load_kube_config()
        logger.info("Loaded kubeconfig from local environment")

    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

    if not pods.items:
        raise Exception(f"No pod found with label selector: {label_selector}")

    pod_name = pods.items[0].metadata.name
    logger.info(f"Found Minecraft pod: {pod_name}")

    return pod_name


@task
def save_world_command(namespace: str, pod_name: str):
    """Execute save-all command in Minecraft server via RCON"""
    logger = get_run_logger()

    try:
        config.load_incluster_config()
    except:
        config.load_kube_config()

    v1 = client.CoreV1Api()

    # Execute save-all command
    exec_command = [
        '/bin/sh', '-c',
        'rcon-cli --password minecraft save-all'
    ]

    logger.info(f"Executing save-all command in pod {pod_name}")
    resp = client.stream(
        v1.connect_get_namespaced_pod_exec,
        pod_name,
        namespace,
        command=exec_command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False
    )

    logger.info(f"Save-all response: {resp}")
    return resp


@task
def copy_world_from_pod(namespace: str, pod_name: str, world_path: str, temp_dir: str):
    """Copy world directory from Minecraft pod to temporary location"""
    logger = get_run_logger()

    # Use kubectl cp command via subprocess
    import subprocess

    source = f"{namespace}/{pod_name}:{world_path}"
    destination = os.path.join(temp_dir, "world")

    cmd = ["kubectl", "cp", source, destination]
    logger.info(f"Copying world from {source} to {destination}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"Failed to copy world: {result.stderr}")

    logger.info(f"Successfully copied world to {destination}")
    return destination


@task
def compress_world(world_dir: str, output_dir: str):
    """Compress world directory using tar.gz"""
    logger = get_run_logger()

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_name = f"minecraft-world-backup-{timestamp}.tar.gz"
    archive_path = os.path.join(output_dir, archive_name)

    logger.info(f"Compressing world to {archive_path}")

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(world_dir, arcname="world")

    file_size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    logger.info(f"Created archive {archive_name} ({file_size_mb:.2f} MB)")

    return archive_path, archive_name


@task
def upload_to_s3(archive_path: str, archive_name: str, s3_path: str):
    """Upload compressed world to S3"""
    logger = get_run_logger()

    # Get AWS credentials and S3 client
    credentials = retrieve_credentials()
    s3_client = get_s3_client(credentials)

    # Parse S3 path (format: s3://bucket-name/prefix)
    s3_path = s3_path.replace("s3://", "")
    parts = s3_path.split("/", 1)
    bucket_name = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""

    s3_key = f"{prefix}/{archive_name}" if prefix else archive_name

    logger.info(f"Uploading to s3://{bucket_name}/{s3_key}")

    s3_client.upload_file(archive_path, bucket_name, s3_key)

    logger.info(f"Successfully uploaded to S3: s3://{bucket_name}/{s3_key}")
    return f"s3://{bucket_name}/{s3_key}"


@task
def cleanup_temp_files(temp_dir: str):
    """Clean up temporary files"""
    logger = get_run_logger()

    import shutil
    shutil.rmtree(temp_dir)

    logger.info(f"Cleaned up temporary directory: {temp_dir}")


@flow(name="minecraft-world-backup")
def world_backup_pipeline():
    """
    Main flow for backing up Minecraft world to S3

    Steps:
    1. Find Minecraft pod using label selector
    2. Execute save-all command via RCON
    3. Copy world directory from pod
    4. Compress world using tar.gz
    5. Upload to S3
    6. Cleanup temporary files
    """
    logger = get_run_logger()

    # Load configuration
    config_path = Path(__file__).parent / "config.json"
    config_data = get_json_config(config_path)

    # Kubernetes configuration
    namespace = "minecraft"
    label_selector = "app=minecraft"
    world_path = "/data/world"

    # Get S3 path from AWS Secrets Manager
    credentials = retrieve_credentials()
    sm_client = get_sm_client(credentials)
    s3_path = retrieve_secret(
        sm_client,
        config_data["s3_secret_name"],
        config_data["s3_secret_key"]
    )

    logger.info(f"S3 backup path: {s3_path}")

    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="minecraft-backup-")
    logger.info(f"Created temporary directory: {temp_dir}")

    try:
        # Execute backup pipeline
        pod_name = get_minecraft_pod(namespace, label_selector)
        save_world_command(namespace, pod_name)
        world_dir = copy_world_from_pod(namespace, pod_name, world_path, temp_dir)
        archive_path, archive_name = compress_world(world_dir, temp_dir)
        s3_location = upload_to_s3(archive_path, archive_name, s3_path)

        logger.info(f"Backup completed successfully: {s3_location}")
        return s3_location

    finally:
        # Always cleanup temporary files
        cleanup_temp_files(temp_dir)

