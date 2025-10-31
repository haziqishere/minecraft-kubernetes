from prefect import flow, task
from datetime import datetime
import subprocess

@task
def backup_minecraft_world():
    """Backup Minecraft world data"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"minecraft_backup_{timestamp}"
    
    # Execute backup via kubectl
    cmd = [
        "kubectl", "exec", "-n", "minecraft",
        "deployment/minecraft-server", "--",
        "rcon-cli", "save-all"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return f"Backup completed: {backup_name}"

@task
def send_notification(message: str):
    """Send notification (placeholder)"""
    print(f"Notification: {message}")
    return "Notification sent"

@flow(name="Minecraft Backup Flow")
def minecraft_backup_flow():
    """Main backup flow"""
    backup_result = backup_minecraft_world()
    notification_result = send_notification(backup_result)
    return backup_result