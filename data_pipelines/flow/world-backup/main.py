from prefect import task, flow, get_run_logger

from utilities.aws_utils import (
    get_s3_client,
    get_sm_client
)

@task
def run_world_backup_pipeline():


    s3_client = get_s3_client()
    sm_client = get_sm_client()

    
    return "Hello World"

@flow
def world_backup_pipeline():

    return run_world_backup_pipeline

