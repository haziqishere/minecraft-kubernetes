import sys  
from pathlib import Path  
  
sys.path.append(str(Path(__file__).parent.parent))  
from flow.public_transit_iceberg_optimized.main import transit_iceberg_optimized_pipeline  
  
if __name__ == "__main__":  
    transit_iceberg_optimized_pipeline.deploy(  
        name="json-to-iceberg-optimized-pipeline",  
        work_pool_name="kubernetes-pool",  
        image="haziqishere/spark-base:latest",
        build=False,  
        push=False,  
        tags=["spark", "iceberg", "json", "optimized"],  
        description="Optimized JSON to Iceberg pipeline with data quality, deduplication, and advanced Iceberg features",  
        job_variables={  
            "namespace": "data-pipeline",  
            "service_account_name": "spark-worker",  
            "image_pull_policy": "Always",  
        },  
    )
