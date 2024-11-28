import json
import boto3
from datetime import datetime

def lambda_handler(event, context):
    try:
        return {
            'statusCode': 200,
            'body': json.dumps('Handler initialized successfully')
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(str(e))
        }
