import boto3
from botocore.exceptions import ClientError

import json


def retrieve_credentials():
    credentials = boto3.Session().get_credentials()
    return {
        "AccessKeyId": credentials.access_key,
        "SecretAccessKey": credentials.secret_key,
        "SessionToken": credentials.token
    }


# S3 #

def get_s3_client(credentials) -> boto3.client:
    if credentials is None:
        s3_client =boto3.client('s3')
    else:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"]
        )

    return s3_client

# SM #

def get_sm_client(credentials=None, region_name="ap-southeast-1") -> boto3.client:
    if credentials is None:
        sm_client = boto3.client('secretsmanager', region_name=region_name)
    else:
        sm_client = boto3.client(
            "secretsmanager",
            region_name=region_name,
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"]
        )

    return sm_client

def retrieve_secret(
    sm_client:boto3.client, secret_name: str, secret_key: str = None
) -> str:
    """
    Use sm_client to retrieve secret value
    """

    try:
        get_secret_value_response = sm_client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e
    
    secret = get_secret_value_response["SecretString"]

    if secret_key is None:
        return secret
    
    secret_dict = json.loads(secret)

    try:
        secret_value = secret_dict[secret_key]
    except KeyError as e:
        raise e
    
    return secret_value


