import boto3
import json
import os
from botocore.exceptions import ClientError
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

    def generate_env_file(self):
        try:
            flask_secret_key = secrets.token_hex(24)
            
            existing_env = {}
            if os.path.exists('.env'):
                with open('.env', 'r') as env_file:
                    for line in env_file:
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            existing_env[key] = value
                            
            env_content = f"""AWS_REGION={existing_env.get('AWS_REGION', 'ap-south-1')}
AWS_ACCESS_KEY_ID={existing_env.get('AWS_ACCESS_KEY_ID', '')}
AWS_SECRET_ACCESS_KEY={existing_env.get('AWS_SECRET_ACCESS_KEY', '')}
FLASK_SECRET_KEY={flask_secret_key}
S3_BUCKET_NAME=sugu-doc-private
FLASK_ENV=development
FLASK_DEBUG=1"""
            
            with open('.env', 'w') as env_file:
                env_file.write(env_content)
            print("\n✅ Updated .env file with new Flask secret key")
            
            if not existing_env.get('AWS_ACCESS_KEY_ID') or not existing_env.get('AWS_SECRET_ACCESS_KEY'):
                print("\n⚠️  WARNING: AWS credentials not found in .env file")
                print("Please manually add your AWS credentials to the .env file:")
                print("AWS_ACCESS_KEY_ID=your_access_key")
                print("AWS_SECRET_ACCESS_KEY=your_secret_key")
        except Exception as e:
            print(f"\nError generating .env file: {str(e)}")
            raise

    def create_dynamodb_tables(self):
        tables = {
            'Employees': {
                'TableName': 'Employees',
                'KeySchema': [
                    {'AttributeName': 'email', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'email', 'AttributeType': 'S'},
                    {'AttributeName': 'employee_id', 'AttributeType': 'S'}
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'EmployeeIdIndex',
                        'KeySchema': [
                            {'AttributeName': 'employee_id', 'KeyType': 'HASH'}
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        }
                    }
                ]
            },
            'LeaveRequests': {
                'TableName': 'LeaveRequests',
                'KeySchema': [
                    {'AttributeName': 'request_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'request_id', 'AttributeType': 'S'},
                    {'AttributeName': 'employee_id', 'AttributeType': 'S'},
                    {'AttributeName': 'created_at', 'AttributeType': 'S'}
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'EmployeeLeaveIndex',
                        'KeySchema': [
                            {'AttributeName': 'employee_id', 'KeyType': 'HASH'},
                            {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        }
                    }
                ]
            },
            'Documents': {
                'TableName': 'Documents',
                'KeySchema': [
                    {'AttributeName': 'document_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'document_id', 'AttributeType': 'S'},
                    {'AttributeName': 'employee_id', 'AttributeType': 'S'},
                    {'AttributeName': 'created_at', 'AttributeType': 'S'}
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'EmployeeDocumentIndex',
                        'KeySchema': [
                            {'AttributeName': 'employee_id', 'KeyType': 'HASH'},
                            {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        }
                    }
                ]
            }
        }

        for table_name, table_config in tables.items():
            try:
                create_params = {
                    'TableName': table_config['TableName'],
                    'KeySchema': table_config['KeySchema'],
                    'AttributeDefinitions': table_config['AttributeDefinitions'],
                    'BillingMode': 'PAY_PER_REQUEST'
                }
                
                if 'GlobalSecondaryIndexes' in table_config:
                    create_params['GlobalSecondaryIndexes'] = table_config['GlobalSecondaryIndexes']
                
                self.dynamodb.create_table(**create_params)
                print(f"Creating table {table_name}...")
                
                waiter = self.dynamodb.get_waiter('table_exists')
                waiter.wait(
                    TableName=table_name,
                    WaiterConfig={'Delay': 5, 'MaxAttempts': 24}
                )
                print(f"✅ Table {table_name} created successfully")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceInUseException':
                    print(f"Table {table_name} already exists")
                    # Update GSIs if needed
                    try:
                        if 'GlobalSecondaryIndexes' in table_config:
                            existing_table = self.dynamodb.describe_table(TableName=table_name)
                            existing_gsis = {
                                gsi['IndexName']: gsi 
                                for gsi in existing_table['Table'].get('GlobalSecondaryIndexes', [])
                            }
                            
                            for gsi in table_config['GlobalSecondaryIndexes']:
                                if gsi['IndexName'] not in existing_gsis:
                                    print(f"Adding GSI {gsi['IndexName']} to {table_name}")
                                    self.dynamodb.update_table(
                                        TableName=table_name,
                                        AttributeDefinitions=table_config['AttributeDefinitions'],
                                        GlobalSecondaryIndexUpdates=[{
                                            'Create': gsi
                                        }]
                                    )
                    except Exception as gsi_error:
                        print(f"Error updating GSIs for {table_name}: {str(gsi_error)}")
                else:
                    raise e

    def create_s3_bucket(self, bucket_name):
        unique_bucket_name = "sugu-doc-private"
        
        try:
            # Create bucket with private access by default
            if self.region == 'us-east-1':
                self.s3.create_bucket(Bucket=unique_bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=unique_bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )

            # Enable server-side encryption
            self.s3.put_bucket_encryption(
                Bucket=unique_bucket_name,
                ServerSideEncryptionConfiguration={
                    'Rules': [
                        {
                            'ApplyServerSideEncryptionByDefault': {
                                'SSEAlgorithm': 'AES256'
                            }
                        }
                    ]
                }
            )

            # Enable versioning
            self.s3.put_bucket_versioning(
                Bucket=unique_bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )

            # Set private access only
            block_public_access = {
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            }
            self.s3.put_public_access_block(
                Bucket=unique_bucket_name,
                PublicAccessBlockConfiguration=block_public_access
            )

            # Set lifecycle policy
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=unique_bucket_name,
                LifecycleConfiguration={
                    'Rules': [
                        {
                            'ID': 'CleanupOldVersions',
                            'Status': 'Enabled',
                            'NoncurrentVersionExpiration': {
                                'NoncurrentDays': 30
                            },
                            'Filter': {}
                        }
                    ]
                }
            )

            print(f"✅ Created private S3 bucket {unique_bucket_name} with enhanced security")
        except ClientError as e:
            if e.response['Error']['Code'] in ['BucketAlreadyExists', 'BucketAlreadyOwnedByYou']:
                print(f"Bucket {unique_bucket_name} already exists")
            else:
                print(f"Error creating S3 bucket: {e}")
                raise e

    def create_default_admin(self):
        try:
            dynamodb = boto3.resource('dynamodb', region_name=self.region)
            table = dynamodb.Table('Employees')
            
            # Create regular admin
            admin_data = {
                'employee_id': str(uuid.uuid4()),
                'email': 'admin@hrms.com',
                'name': 'Admin User',
                'password': bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
                'department': 'Administration',
                'position': 'System Admin',
                'is_admin': True,
                'is_super_admin': False,
                'created_at': datetime.now().isoformat(),
                'created_by': 'system'
            }
            
            # Create super admin
            super_admin_data = {
                'employee_id': str(uuid.uuid4()),
                'email': 'superadmin@hrms.com',
                'name': 'Super Admin',
                'password': bcrypt.hashpw('superadmin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
                'department': 'Administration',
                'position': 'Super Administrator',
                'is_admin': True,
                'is_super_admin': True,
                'created_at': datetime.now().isoformat(),
                'created_by': 'system'
            }
            
            # Check if admin exists
            response = table.get_item(Key={'email': 'admin@hrms.com'})
            if 'Item' not in response:
                table.put_item(Item=admin_data)
                print("\n✅ Created default admin user (admin@hrms.com / admin123)")
            else:
                print("\nℹ️ Admin user already exists")
                
            # Check if super admin exists
            response = table.get_item(Key={'email': 'superadmin@hrms.com'})
            if 'Item' not in response:
                table.put_item(Item=super_admin_data)
                print("✅ Created super admin user (superadmin@hrms.com / superadmin123)")
            else:
                print("ℹ️ Super admin user already exists")
                
        except Exception as e:
            print(f"Error creating default admins: {str(e)}")
            raise

def main():
    try:
        hrms = HRMSInfrastructure()
        
        print("\n🚀 Starting HRMS infrastructure setup...")
        
        os.makedirs('infrastructure', exist_ok=True)
        os.makedirs('src/lambda', exist_ok=True)
        
        print("\n📝 Generating environment file...")
        hrms.generate_env_file()
        
        print("\n🗄️ Creating DynamoDB tables...")
        hrms.create_dynamodb_tables()
        
        print("\n📦 Setting up S3 bucket...")
        hrms.create_s3_bucket('sugu-doc-private')
        
        print("\n👤 Creating admin users...")
        hrms.create_default_admin()

        print("\n✨ HRMS infrastructure setup completed successfully!")
        print("📌 The .env file has been updated with all required configurations")
        print("🚀 Run 'python src/web/app.py' to start the application")
        
    except Exception as e:
        print(f"\n❌ Error during setup: {str(e)}")
        raise

if __name__ == "__main__":
    main()
