import sys  
from pathlib import Path  
from prefect.schedules import CronSchedule
  
sys.path.append(str(Path(__file__).parent.parent))  
from flow.public_transit_iceberg_optimized.main import transit_iceberg_optimized_pipeline  
  
if __name__ == "__main__":  
    transit_iceberg_optimized_pipeline.deploy(  
        name="json-to-iceberg-optimized-pipeline",  
        work_pool_name="kubernetes-pool",  
        image="haziqishere/spark-base:latest",
        build=False,  
        push=False,  
        tags=["spark", "iceberg", "json", "optimized", "hourly"],  
        description="Optimized JSON to Iceberg pipeline with hourly scheduling, data quality, deduplication, and advanced Iceberg features",  
        schedule=CronSchedule(cron="0 * * * *", timezone="Asia/Kuala_Lumpur"),  # Run every hour at minute 0
        job_variables={
            "namespace": "prefect",
            "service_account_name": "prefect-worker",
            "image_pull_policy": "Always",
        },  
        parameters={  
            "input_path": "s3://public-transport-dataset/raw/transit-positions",  
            "output_table": "glue_catalog.public_transport.vehicle_positions",  
            "enable_validation": True,  
            "enable_deduplication": True,  
            "min_quality_score": 3,  
            "hours_back": 2,  
            "use_hourly_partitions": True  
        }  
    )
