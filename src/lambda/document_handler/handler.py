import json
import boto3
import uuid
from datetime import datetime

def lambda_handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    s3 = boto3.client('s3')
    table = dynamodb.Table('Documents')
    bucket_name = 'hrms-documents-bucket'
    
    try:
        operation = event.get('operation')
        
        if operation == 'upload':
            document_data = event.get('document', {})
            document_data['document_id'] = str(uuid.uuid4())
            document_data['created_at'] = datetime.now().isoformat()
            
            # Generate pre-signed URL for upload
            s3_key = f"{document_data['employee_id']}/{document_data['document_id']}/{document_data['filename']}"
            upload_url = s3.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': s3_key
                },
                ExpiresIn=3600
            )
            
            document_data['s3_key'] = s3_key
            table.put_item(Item=document_data)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Document record created successfully',
                    'document_id': document_data['document_id'],
                    'upload_url': upload_url
                })
            }
            
        elif operation == 'get':
            document_id = event.get('document_id')
            response = table.get_item(Key={'document_id': document_id})
            document = response.get('Item')
            
            if document:
                # Generate download URL
                download_url = s3.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': bucket_name,
                        'Key': document['s3_key']
                    },
                    ExpiresIn=3600
                )
                document['download_url'] = download_url
            
            return {
                'statusCode': 200,
                'body': json.dumps(document)
            }
            
        elif operation == 'list':
            employee_id = event.get('employee_id')
            response = table.scan()
            documents = response.get('Items', [])
            
            if employee_id:
                documents = [d for d in documents if d.get('employee_id') == employee_id]
                
            # Generate download URLs for all documents
            for doc in documents:
                doc['download_url'] = s3.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': bucket_name,
                        'Key': doc['s3_key']
                    },
                    ExpiresIn=3600
                )
                
            return {
                'statusCode': 200,
                'body': json.dumps(documents)
            }
            
        elif operation == 'delete':
            document_id = event.get('document_id')
            response = table.get_item(Key={'document_id': document_id})
            document = response.get('Item')
            
            if document:
                # Delete from S3
                s3.delete_object(
                    Bucket=bucket_name,
                    Key=document['s3_key']
                )
                # Delete from DynamoDB
                table.delete_item(Key={'document_id': document_id})
            
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Document deleted successfully'})
            }
            
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid operation'})
            }
            
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
