import boto3
import json
import time
from botocore.exceptions import ClientError
import sys
import os

class HRMSCleanup:
    def __init__(self, region='ap-south-1'):
        self.region = region
        self.dynamodb = boto3.client('dynamodb', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.iam = boto3.client('iam', region_name=region)
        
    def confirm_cleanup(self):
        print("\n⚠️  WARNING: This will delete all HRMS resources from AWS!")
        print("This includes all data in DynamoDB tables, S3 buckets, and Lambda functions.")
        confirm = input("\nAre you sure you want to proceed? (type 'yes' to confirm): ")
        return confirm.lower() == 'yes'

    def delete_dynamodb_tables(self):
        tables = ['Employees', 'LeaveRequests', 'Documents']
        
        print("\n🗑️  Cleaning up DynamoDB tables...")
        for table_name in tables:
            try:
                self.dynamodb.delete_table(TableName=table_name)
                print(f"  ✓ Initiated deletion of table: {table_name}")
                
                print(f"  ⏳ Waiting for {table_name} table to be deleted...")
                waiter = self.dynamodb.get_waiter('table_not_exists')
                waiter.wait(
                    TableName=table_name,
                    WaiterConfig={'Delay': 5, 'MaxAttempts': 24}
                )
                print(f"  ✓ Table {table_name} deleted successfully")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"  ℹ️  Table {table_name} does not exist")
                else:
                    print(f"  ❌ Error deleting table {table_name}: {str(e)}")

    def empty_and_delete_s3_bucket(self, bucket_name):
        print(f"\n🗑️  Cleaning up S3 bucket: {bucket_name}")
        try:
            # Delete all object versions first
            paginator = self.s3.get_paginator('list_object_versions')
            try:
                for page in paginator.paginate(Bucket=bucket_name):
                    delete_keys = []
                    if 'Versions' in page:
                        delete_keys.extend([
                            {'Key': obj['Key'], 'VersionId': obj['VersionId']}
                            for obj in page['Versions']
                        ])
                    if 'DeleteMarkers' in page:
                        delete_keys.extend([
                            {'Key': obj['Key'], 'VersionId': obj['VersionId']}
                            for obj in page['DeleteMarkers']
                        ])
                    
                    if delete_keys:
                        self.s3.delete_objects(
                            Bucket=bucket_name,
                            Delete={'Objects': delete_keys}
                        )
                        print(f"  ✓ Deleted {len(delete_keys)} object versions")
            except ClientError:
                # Bucket might not have versioning enabled
                pass

            # Delete remaining objects
            paginator = self.s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    objects = [{'Key': obj['Key']} for obj in page['Contents']]
                    self.s3.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': objects}
                    )
                    print(f"  ✓ Deleted {len(objects)} objects")
            
            # Remove bucket policy and CORS if they exist
            try:
                self.s3.delete_bucket_policy(Bucket=bucket_name)
                self.s3.delete_bucket_cors(Bucket=bucket_name)
            except ClientError:
                pass

            # Remove public access block
            try:
                self.s3.put_public_access_block(
                    Bucket=bucket_name,
                    PublicAccessBlockConfiguration={
                        'BlockPublicAcls': False,
                        'IgnorePublicAcls': False,
                        'BlockPublicPolicy': False,
                        'RestrictPublicBuckets': False
                    }
                )
            except ClientError:
                pass

            # Finally delete the bucket
            time.sleep(2)  # Wait for configurations to propagate
            self.s3.delete_bucket(Bucket=bucket_name)
            print(f"  ✓ Bucket {bucket_name} deleted successfully")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"  ℹ️  Bucket {bucket_name} does not exist")
            else:
                print(f"  ❌ Error deleting bucket {bucket_name}: {str(e)}")

    def delete_lambda_functions(self):
        functions = ['employee_handler', 'leave_handler', 'document_handler']
        
        print("\n🗑️  Cleaning up Lambda functions...")
        for function_name in functions:
            try:
                self.lambda_client.delete_function(FunctionName=function_name)
                print(f"  ✓ Function {function_name} deleted successfully")
                time.sleep(2)
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"  ℹ️  Function {function_name} does not exist")
                else:
                    print(f"  ❌ Error deleting function {function_name}: {str(e)}")

    def delete_iam_role(self):
        role_name = 'hrms-lambda-role'
        
        print("\n🗑️  Cleaning up IAM role...")
        try:
            # Detach policies first
            policies = [
                'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
                'arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess',
                'arn:aws:iam::aws:policy/AmazonS3FullAccess'
            ]
            
            for policy in policies:
                try:
                    self.iam.detach_role_policy(
                        RoleName=role_name,
                        PolicyArn=policy
                    )
                    print(f"  ✓ Detached policy: {policy}")
                except ClientError as e:
                    if e.response['Error']['Code'] != 'NoSuchEntity':
                        print(f"  ❌ Error detaching policy {policy}: {str(e)}")
            
            time.sleep(2)
            self.iam.delete_role(RoleName=role_name)
            print(f"  ✓ Role {role_name} deleted successfully")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"  ℹ️  Role {role_name} does not exist")
            else:
                print(f"  ❌ Error deleting role {role_name}: {str(e)}")

    def cleanup_local_files(self):
        print("\n🗑️  Cleaning up local configuration files...")
        files_to_delete = ['.env', 'infrastructure/config.json']
        
        for file_path in files_to_delete:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"  ✓ Deleted {file_path}")
                else:
                    print(f"  ℹ️  File {file_path} does not exist")
            except Exception as e:
                print(f"  ❌ Error deleting {file_path}: {str(e)}")

def main():
    try:
        cleanup = HRMSCleanup()
        
        if not cleanup.confirm_cleanup():
            print("\n❌ Cleanup cancelled by user")
            sys.exit(0)
        
        print("\n🚀 Starting HRMS cleanup process...")
        
        cleanup.delete_lambda_functions()
        cleanup.delete_iam_role()
        cleanup.empty_and_delete_s3_bucket('hrms-documents-bucket')
        cleanup.delete_dynamodb_tables()
        cleanup.cleanup_local_files()
        
        print("\n✨ HRMS cleanup completed successfully!")
        print("All AWS resources and local configuration files have been removed.")
        
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
