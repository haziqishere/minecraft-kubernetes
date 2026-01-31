import sys  
from pathlib import Path  
# from prefect.schedules import CronSchedule
  
sys.path.append(str(Path(__file__).parent.parent))  
from spark_flow.public_transit_iceberg_optimized.main import transit_iceberg_optimized_pipeline  
  
if __name__ == "__main__":  
    transit_iceberg_optimized_pipeline.deploy(  
        name="json-to-iceberg-optimized-pipeline",  
        work_pool_name="kubernetes-pool",  
        image="haziqishere/spark-base:latest",
        build=False,  
        push=False,  
        tags=["spark", "iceberg", "json", "optimized", "hourly"],  
        description="Optimized JSON to Iceberg pipeline with hourly scheduling, data quality, deduplication, and advanced Iceberg features",  
        # schedule=CronSchedule(cron="0 * * * *", timezone="Asia/Kuala_Lumpur"),  # Run every hour at minute 0
        job_variables={
            "namespace": "minecraft",
            "service_account_name": "prefect-worker",
            "image_pull_policy": "Always",
            "env": {
                "PREFECT_API_EVENTS_ENABLED": "false",
                "AWS_REGION": "ap-southeast-1",
                "AWS_DEFAULT_REGION": "ap-southeast-1",
            },
        },  
    )
