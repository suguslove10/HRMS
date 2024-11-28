import boto3
import json
import os
from botocore.exceptions import ClientError
import io
import zipfile
import secrets
import time
from dotenv import load_dotenv
from datetime import datetime
import uuid
import bcrypt

class HRMSInfrastructure:
    def __init__(self, region='ap-south-1'):
        self.region = region
        self.dynamodb = boto3.client('dynamodb', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.iam = boto3.client('iam', region_name=region)

    def generate_env_file(self, credentials):
        try:
            flask_secret_key = secrets.token_hex(24)
            env_content = f"""AWS_REGION={self.region}
AWS_ACCESS_KEY_ID={credentials['access_key']}
AWS_SECRET_ACCESS_KEY={credentials['secret_key']}
FLASK_SECRET_KEY={flask_secret_key}
S3_BUCKET_NAME=hrms-documents-bucket
FLASK_ENV=development
FLASK_DEBUG=1"""
            
            with open('.env', 'w') as env_file:
                env_file.write(env_content)
            print("Generated .env file with secure Flask secret key")
        except Exception as e:
            print(f"Error generating .env file: {str(e)}")
            raise

    def create_dynamodb_tables(self):
        tables = {
            'Employees': {
                'KeySchema': [
                    {'AttributeName': 'email', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'email', 'AttributeType': 'S'}
                ]
            },
            'LeaveRequests': {
                'KeySchema': [
                    {'AttributeName': 'request_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'request_id', 'AttributeType': 'S'}
                ]
            },
            'Documents': {
                'KeySchema': [
                    {'AttributeName': 'document_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'document_id', 'AttributeType': 'S'}
                ]
            }
        }

        for table_name, schema in tables.items():
            try:
                self.dynamodb.create_table(
                    TableName=table_name,
                    KeySchema=schema['KeySchema'],
                    AttributeDefinitions=schema['AttributeDefinitions'],
                    BillingMode='PAY_PER_REQUEST'
                )
                print(f"Created table {table_name}")
                waiter = self.dynamodb.get_waiter('table_exists')
                waiter.wait(
                    TableName=table_name,
                    WaiterConfig={'Delay': 5, 'MaxAttempts': 24}
                )
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceInUseException':
                    print(f"Table {table_name} already exists")
                else:
                    raise e

    def create_s3_bucket(self, bucket_name):
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "FullAccess",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:*"],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*"
                ]
            }]
        }

        try:
            if self.region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )

            # Configure bucket permissions
            self.s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))
            self.s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': False,
                    'IgnorePublicAcls': False,
                    'BlockPublicPolicy': False,
                    'RestrictPublicBuckets': False
                }
            )

            # Enable CORS
            cors_config = {
                'CORSRules': [{
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'PUT', 'POST', 'DELETE'],
                    'AllowedOrigins': ['*'],
                    'ExposeHeaders': []
                }]
            }
            self.s3.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_config)

            print(f"Created S3 bucket {bucket_name}")
        except ClientError as e:
            if e.response['Error']['Code'] in ['BucketAlreadyExists', 'BucketAlreadyOwnedByYou']:
                print(f"Bucket {bucket_name} already exists")
            else:
                raise e

    def create_default_admin(self):
        try:
            dynamodb = boto3.resource('dynamodb', region_name=self.region)
            table = dynamodb.Table('Employees')
            
            admin_data = {
                'employee_id': str(uuid.uuid4()),
                'email': 'admin@hrms.com',
                'name': 'Admin User',
                'password': bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
                'department': 'Administration',
                'position': 'System Admin',
                'is_admin': True,
                'created_at': datetime.now().isoformat()
            }
            
            table.put_item(Item=admin_data)
            print("Created default admin user (admin@hrms.com / admin123)")
        except Exception as e:
            print(f"Error creating default admin: {str(e)}")
            raise

def main():
    try:
        credentials = {
            'access_key': 'youraccesskey',
            'secret_key': 'yoursecretkey'
        }

        hrms = HRMSInfrastructure()
        
        os.makedirs('infrastructure', exist_ok=True)
        os.makedirs('src/lambda', exist_ok=True)
        
        hrms.generate_env_file(credentials)
        hrms.create_dynamodb_tables()
        hrms.create_s3_bucket('hrms-documents-bucket')
        hrms.create_default_admin()

        print("\nHRMS infrastructure setup completed successfully!")
        print("The .env file has been updated with all required configurations")
        print("Run 'python src/web/app.py' to start the application")
        
    except Exception as e:
        print(f"\nError during setup: {str(e)}")
        raise

if __name__ == "__main__":
    main()
