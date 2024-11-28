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
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.iam = boto3.client('iam', region_name=region)

    def generate_env_file(self, credentials):
        """Generate .env file with necessary configurations"""
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
        try:
            if self.region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={
                        'LocationConstraint': self.region
                    }
                )
            print(f"Created S3 bucket {bucket_name}")
            
            self.s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            
            self.s3.put_bucket_encryption(
                Bucket=bucket_name,
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
            
        except ClientError as e:
            if e.response['Error']['Code'] in ['BucketAlreadyExists', 'BucketAlreadyOwnedByYou']:
                print(f"Bucket {bucket_name} already exists")
            else:
                raise e

    def create_lambda_role(self):
        role_name = 'hrms-lambda-role'
        try:
            role_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }

            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(role_policy)
            )

            policies = [
                'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
                'arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess',
                'arn:aws:iam::aws:policy/AmazonS3FullAccess'
            ]

            for policy in policies:
                self.iam.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy
                )

            print(f"Created Lambda role {role_name}")
            print("Waiting for IAM role to propagate...")
            time.sleep(10)
            
            return response['Role']['Arn']
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                print(f"Role {role_name} already exists")
                response = self.iam.get_role(RoleName=role_name)
                return response['Role']['Arn']
            else:
                raise e

    def create_default_admins(self):
        try:
            dynamodb = boto3.resource('dynamodb', region_name=self.region)
            table = dynamodb.Table('Employees')
            
            def hash_password(password):
                return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            default_admins = [
                {
                    'employee_id': str(uuid.uuid4()),
                    'email': 'admin@hrms.com',
                    'password': hash_password('admin123'),
                    'name': 'Admin User',
                    'department': 'Administration',
                    'position': 'System Admin',
                    'is_admin': True,
                    'created_at': datetime.now().isoformat()
                },
                {
                    'employee_id': str(uuid.uuid4()),
                    'email': 'hradmin@hrms.com',
                    'password': hash_password('hr123'),
                    'name': 'HR Admin',
                    'department': 'Human Resources',
                    'position': 'HR Manager',
                    'is_admin': True,
                    'created_at': datetime.now().isoformat()
                }
            ]
            
            for admin in default_admins:
                try:
                    response = table.get_item(
                        Key={'email': admin['email']}
                    )
                    if 'Item' not in response:
                        print(f"\nCreating admin account: {admin['email']}")
                        table.put_item(Item=admin)
                        print(f"✓ Created admin account: {admin['email']}")
                    else:
                        print(f"\nAdmin account already exists: {admin['email']}")
                        
                    verify = table.get_item(
                        Key={'email': admin['email']}
                    )
                    if 'Item' in verify:
                        print(f"✓ Verified admin account exists: {admin['email']}")
                    else:
                        print(f"❌ Failed to verify admin account: {admin['email']}")
                        
                except Exception as e:
                    print(f"❌ Error processing admin {admin['email']}: {str(e)}")
            
            print("\n✓ Default admin accounts processed")
            
        except Exception as e:
            print(f"\n❌ Error creating default admins: {str(e)}")
            raise

    def create_lambda_functions(self, role_arn):
        lambda_functions = {
            'employee_handler': 'Employee management handler',
            'leave_handler': 'Leave request handler',
            'document_handler': 'Document management handler'
        }

        function_arns = {}
        
        # Create basic handler code first
        for func_name in lambda_functions:
            dir_path = f'src/lambda/{func_name}'
            os.makedirs(dir_path, exist_ok=True)
            
            with open(f'{dir_path}/handler.py', 'w') as f:
                f.write('''import json
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
''')

        # Create/Update Lambda functions
        for func_name, description in lambda_functions.items():
            try:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    handler_path = f'src/lambda/{func_name}/handler.py'
                    zip_file.write(handler_path, 'handler.py')

                zip_buffer.seek(0)

                try:
                    response = self.lambda_client.create_function(
                        FunctionName=func_name,
                        Runtime='python3.9',
                        Role=role_arn,
                        Handler='handler.lambda_handler',
                        Code={'ZipFile': zip_buffer.read()},
                        Description=description,
                        Timeout=30,
                        MemorySize=128,
                        Publish=True,
                        Environment={
                            'Variables': {
                                'REGION': self.region,
                                'S3_BUCKET': 'hrms-documents-bucket'
                            }
                        }
                    )
                    function_arns[func_name] = response['FunctionArn']
                    print(f"Created Lambda function: {func_name}")
                    
                except self.lambda_client.exceptions.ResourceConflictException:
                    print(f"Updating existing Lambda function: {func_name}")
                    zip_buffer.seek(0)
                    self.lambda_client.update_function_code(
                        FunctionName=func_name,
                        ZipFile=zip_buffer.read()
                    )
                    response = self.lambda_client.get_function(FunctionName=func_name)
                    function_arns[func_name] = response['Configuration']['FunctionArn']
                
                time.sleep(5)
                
            except Exception as e:
                print(f"Error with Lambda function {func_name}: {str(e)}")
                raise

        return function_arns

def main():
    try:
        # AWS credentials
        credentials = {
            'access_key': 'AKIATCKAM3ED6I3FYSFF',
            'secret_key': '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'
        }

        # Initialize infrastructure
        hrms = HRMSInfrastructure()
        
        # Create necessary directories
        os.makedirs('infrastructure', exist_ok=True)
        os.makedirs('src/lambda', exist_ok=True)
        
        # Generate .env file first
        hrms.generate_env_file(credentials)

        # Create resources
        print("\nCreating DynamoDB tables...")
        hrms.create_dynamodb_tables()
        
        print("\nCreating default admin accounts...")
        hrms.create_default_admins()
        
        print("\nCreating S3 bucket...")
        hrms.create_s3_bucket('hrms-documents-bucket')
        
        print("\nSetting up Lambda functions...")
        lambda_role_arn = hrms.create_lambda_role()
        function_arns = hrms.create_lambda_functions(lambda_role_arn)

        # Save configuration
        config = {
            'region': hrms.region,
            'lambda_role_arn': lambda_role_arn,
            'function_arns': function_arns,
            's3_bucket': 'hrms-documents-bucket'
        }

        with open('infrastructure/config.json', 'w') as f:
            json.dump(config, f, indent=2)

        print("\n✨ HRMS infrastructure setup completed successfully!")
        print("🔑 The .env file has been updated with all required configurations")
        print("▶️  Run 'python src/web/app.py' to start the application")
        
    except Exception as e:
        print(f"\n❌ Error during setup: {str(e)}")
        raise

if __name__ == "__main__":
    main()