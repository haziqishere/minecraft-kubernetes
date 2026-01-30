# AWS Glue Catalog and Iceberg Setup Guide

This guide will help you set up the required AWS resources for the Iceberg public transport pipeline.

## Prerequisites
- AWS account with appropriate permissions
- AWS CLI configured
- S3 bucket for data storage (e.g., `s3://public-transport-dataset/`)

## 1. AWS Glue Catalog Setup

### 1.1 Create Glue Database
```bash
aws glue create-database \
    --database-input '{
        "Name": "public_transport",
        "Description": "Database for public transport data"
    }'
```

### 1.2 Verify Glue Database
```bash
aws glue get-database --name public_transport
```

## 2. IAM Role Configuration

### 2.1 Create IAM Policy for Spark/Iceberg Access
Create a file named `iceberg-spark-policy.json`:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::public-transport-dataset",
                "arn:aws:s3:::public-transport-dataset/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "glue:GetDatabase",
                "glue:GetTable",
                "glue:GetTables",
                "glue:CreateDatabase",
                "glue:CreateTable",
                "glue:UpdateTable",
                "glue:DeleteTable",
                "glue:GetPartition",
                "glue:GetPartitions",
                "glue:CreatePartition",
                "glue:BatchCreatePartition",
                "glue:UpdatePartition",
                "glue:DeletePartition",
                "glue:BatchDeletePartition"
            ],
            "Resource": [
                "arn:aws:glue:*:*:catalog",
                "arn:aws:glue:*:*:database/public_transport",
                "arn:aws:glue:*:*:table/public_transport/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "lakeformation:GetDataAccess",
                "lakeformation:GrantPermissions"
            ],
            "Resource": "*"
        }
    ]
}
```

### 2.2 Create the IAM Policy
```bash
aws iam create-policy \
    --policy-name IcebergSparkAccessPolicy \
    --policy-document file://iceberg-spark-policy.json
```

### 2.3 Create IAM Role for Kubernetes Service Account
Create a file named `trust-relationship.json`:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/CLUSTER_ID"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "oidc.eks.REGION.amazonaws.com/id/CLUSTER_ID:sub": "system:serviceaccount:data-pipeline:spark-worker"
                }
            }
        }
    ]
}
```

Replace:
- `ACCOUNT_ID` with your AWS account ID
- `REGION` with your AWS region (e.g., `ap-southeast-1`)
- `CLUSTER_ID` with your EKS cluster ID

### 2.4 Create the IAM Role
```bash
aws iam create-role \
    --role-name spark-worker-iceberg-role \
    --assume-role-policy-document file://trust-relationship.json
```

### 2.5 Attach Policy to Role
```bash
aws iam attach-role-policy \
    --role-name spark-worker-iceberg-role \
    --policy-arn arn:aws:iam::ACCOUNT_ID:policy/IcebergSparkAccessPolicy
```

## 3. Lake Formation Setup (Optional but Recommended)

### 3.1 Register S3 Location with Lake Formation
```bash
aws lakeformation register-resource \
    --resource-arn arn:aws:s3:::public-transport-dataset \
    --role-arn arn:aws:iam::ACCOUNT_ID:role/spark-worker-iceberg-role \
    --use-service-linked-role
```

### 3.2 Grant Permissions to Database
```bash
aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=arn:aws:iam::ACCOUNT_ID:role/spark-worker-iceberg-role \
    --permissions CREATE DESCRIBE ALTER DROP \
    --resource '{ "Database": { "Name": "public_transport" } }'
```

### 3.3 Grant Table Permissions
```bash
aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=arn:aws:iam::ACCOUNT_ID:role/spark-worker-iceberg-role \
    --permissions SELECT INSERT ALTER DELETE \
    --resource '{ "Table": { "DatabaseName": "public_transport", "Name": "vehicle_positions" } }'
```

## 4. Kubernetes Service Account Setup

### 4.1 Create Service Account with IAM Role Annotation
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spark-worker
  namespace: data-pipeline
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/spark-worker-iceberg-role
```

### 4.2 Apply Service Account
```bash
kubectl apply -f service-account.yaml
```

## 5. Verification

### 5.1 Test S3 Access
```bash
aws s3 ls s3://public-transport-dataset/
```

### 5.2 Test Glue Access
```bash
aws glue get-databases
```

### 5.3 Test Lake Formation Permissions
```bash
aws lakeformation list-permissions --resource '{ "Database": { "Name": "public_transport" } }'
```

## 6. Troubleshooting

### Common Issues:
1. **Access Denied**: Check IAM role permissions and trust relationship
2. **Glue Database Not Found**: Ensure database is created in correct region
3. **S3 Access Issues**: Verify S3 bucket policies and IAM permissions
4. **Lake Formation Permissions**: Ensure proper grants are in place

### Debug Commands:
```bash
# Check IAM role
aws iam get-role --role-name spark-worker-iceberg-role

# Check attached policies
aws iam list-attached-role-policies --role-name spark-worker-iceberg-role

# Check Glue databases
aws glue get-databases

# Check S3 bucket permissions
aws s3api get-bucket-policy --bucket public-transport-dataset
```

## 7. Environment Variables for Prefect Flow

Ensure your Prefect deployment has these environment variables:
- `AWS_REGION`: Your AWS region (e.g., `ap-southeast-1`)
- `AWS_ACCESS_KEY_ID`: If not using IRSA
- `AWS_SECRET_ACCESS_KEY`: If not using IRSA

For Kubernetes deployment with IRSA (IAM Roles for Service Accounts), you don't need to set AWS credentials as environment variables.
