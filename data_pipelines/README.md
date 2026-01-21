# Minecraft World Backup Pipeline

This Prefect pipeline automates backing up your Minecraft world to AWS S3 with lossless compression.

## Features

- Finds Minecraft pod dynamically using label selectors (works with ArgoCD deployments)
- Executes `save-all` command via RCON before backup
- Copies world directory from pod using kubectl
- Compresses world using tar.gz (lossless compression)
- Uploads to S3 with timestamped filenames
- Automatic cleanup of temporary files
- Runs on a schedule (default: every 6 hours)

## Prerequisites

1. **Prefect Server** running in your k3s cluster
2. **AWS Credentials** configured (via `aws login` or IAM role)
3. **AWS Secrets Manager** with S3 path configuration
4. **Kubernetes RBAC** permissions for the Prefect worker

## Setup Instructions

### 1. Configure AWS Secrets Manager

Create a secret in AWS Secrets Manager with your S3 backup path:

```json
{
  "world_backup_s3_path": "s3://your-bucket/minecraft/backups"
}
```

Update `data_pipelines/flow/world-backup/config.json` with your secret name:

```json
{
    "s3_secret_name": "prod-s3-path",
    "s3_secret_key": "world_backup_s3_path"
}
```

### 2. Deploy Kubernetes RBAC

The Prefect worker needs permissions to:
- List and get pods in the minecraft namespace
- Execute commands in pods (for kubectl cp and RCON)

Apply the RBAC configuration:

```bash
kubectl apply -f kubernetes/prefect/rbac.yaml
```

### 3. Build and Push Docker Image

The CI pipeline will automatically build and push the image when you:
- Push to main branch
- Modify files in `docker/python-general/` or `data_pipelines/`

Or manually trigger the build:

```bash
# Via GitHub Actions UI
# Or push your changes
git add .
git commit -m "Update backup pipeline"
git push origin nonprod
```

The image will be pushed to: `haziqishere/python-general:latest`

### 4. Configure AWS Credentials in k3s

On your k3s node, ensure AWS credentials are configured:

```bash
# SSH into your k3s node
aws configure

# Or use AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
```

Alternatively, mount AWS credentials into the Prefect worker pod by updating the deployment script.

### 5. Deploy to Prefect

From your MacBook (within Tailscale VPN):

```bash
# Set Prefect API URL to your homelab Prefect server
export PREFECT_API_URL="http://your-prefect-server:4200/api"

# Deploy the flow
cd data_pipelines
python deployment/deploy_world_backup.py
```

This creates a deployment that:
- Runs every 6 hours (configurable via cron schedule)
- Uses `haziqishere/python-general:latest` image
- Runs in the `minecraft` namespace
- Uses the `prefect-worker` service account

### 6. Verify Deployment

```bash
# List deployments
prefect deployment ls

# Run a test backup
prefect deployment run "minecraft-world-backup/minecraft-world-backup"

# View flow runs
prefect flow-run ls
```

## Configuration

### Kubernetes Settings

Edit `data_pipelines/flow/world-backup/main.py` to customize:

```python
# Kubernetes configuration
namespace = "minecraft"
label_selector = "app=minecraft"
world_path = "/data/world"
```

### Backup Schedule

Edit `data_pipelines/deployment/deploy_world_backup.py` to change the schedule:

```python
schedule=CronSchedule(cron="0 */6 * * *"),  # Every 6 hours
# Examples:
# "0 0 * * *"     # Daily at midnight
# "0 */12 * * *"  # Every 12 hours
# "0 2 * * 0"     # Weekly on Sunday at 2 AM
```

### Work Pool Name

Update the work pool name in `deploy_world_backup.py` to match your Prefect setup:

```python
work_pool_name="kubernetes-pool",  # Change to your work pool name
```

## Manual Execution

To manually trigger a backup:

```bash
# Via Prefect CLI
prefect deployment run "minecraft-world-backup/minecraft-world-backup"

# Or via Prefect UI
# Navigate to Deployments → minecraft-world-backup → Run
```

## Troubleshooting

### "No pod found with label selector"

Verify the Minecraft pod has the correct label:

```bash
kubectl get pods -n minecraft --show-labels
# Should show: app=minecraft
```

### "Failed to copy world"

Check RBAC permissions:

```bash
kubectl auth can-i create pods/exec -n minecraft --as=system:serviceaccount:minecraft:prefect-worker
# Should return "yes"
```

### "AWS credentials not found"

Ensure AWS credentials are available in the Prefect worker pod:

```bash
# Check if credentials are configured
kubectl exec -n minecraft <prefect-worker-pod> -- aws sts get-caller-identity
```

### Import errors

Verify the working directory is set correctly in the Docker image:

```bash
# Check image working directory
docker run haziqishere/python-general:latest pwd
# Should output: /app/data_pipelines
```

## File Structure

```
data_pipelines/
├── deployment/
│   └── deploy_world_backup.py  # Prefect deployment script
├── flow/
│   └── world-backup/
│       ├── config.json          # AWS Secrets Manager configuration
│       └── main.py              # Main backup pipeline
└── utilities/
    ├── aws_utils.py             # AWS S3 and Secrets Manager utilities
    └── config_utils.py          # Configuration file utilities

kubernetes/prefect/
└── rbac.yaml                    # Kubernetes RBAC configuration (apply once)
```

## Pipeline Flow

1. **Find Pod**: Locate Minecraft pod using `app=minecraft` label
2. **Save World**: Execute `save-all` via RCON to ensure data consistency
3. **Copy Files**: Use `kubectl cp` to copy `/data/world` from pod
4. **Compress**: Create timestamped `tar.gz` archive
5. **Upload**: Upload to S3 path from Secrets Manager
6. **Cleanup**: Remove temporary files

## Backup File Format

Backups are saved with the following naming pattern:

```
minecraft-world-backup-YYYYMMDD-HHMMSS.tar.gz
```

Example: `minecraft-world-backup-20260121-143000.tar.gz`

## Next Steps

- Set up S3 lifecycle policies to archive old backups to Glacier
- Configure SNS notifications for backup failures
- Add world restore functionality
- Implement backup verification/testing
