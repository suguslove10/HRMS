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
            # Empty the bucket
            print(f"  ⏳ Emptying bucket {bucket_name}...")
            paginator = self.s3.get_paginator('list_object_versions')
            page_iterator = paginator.paginate(Bucket=bucket_name)

            delete_us = dict(Objects=[])
            for page in page_iterator:
                if 'Versions' in page:
                    for version in page['Versions']:
                        delete_us['Objects'].append(dict(Key=version['Key'], VersionId=version['VersionId']))

                if 'DeleteMarkers' in page:
                    for marker in page['DeleteMarkers']:
                        delete_us['Objects'].append(dict(Key=marker['Key'], VersionId=marker['VersionId']))
                        
                if len(delete_us['Objects']) >= 1000:
                    self.s3.delete_objects(Bucket=bucket_name, Delete=delete_us)
                    delete_us = dict(Objects=[])

            if len(delete_us['Objects']):
                self.s3.delete_objects(Bucket=bucket_name, Delete=delete_us)
            
            print(f"  ✓ Bucket {bucket_name} emptied successfully")
            
            # Delete the bucket
            print(f"  ⏳ Deleting bucket {bucket_name}...")
            self.s3.delete_bucket(Bucket=bucket_name)
            print(f"  ✓ Bucket {bucket_name} deleted successfully")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"  ℹ️  Bucket {bucket_name} does not exist")
            else:
                print(f"  ❌ Error cleaning up bucket {bucket_name}: {str(e)}")

    def cleanup_local_files(self):
        print("\n🗑️  Cleaning up local configuration files...")
        files_to_delete = ['.env']
        
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
        
        cleanup.empty_and_delete_s3_bucket('sugu-doc-private')
        cleanup.delete_dynamodb_tables()
        cleanup.cleanup_local_files()
        
        print("\n✨ HRMS cleanup completed successfully!")
        print("All AWS resources and local configuration files have been removed.")
        
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
