import json
import boto3
import uuid
from datetime import datetime

def lambda_handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('LeaveRequests')
    
    try:
        operation = event.get('operation')
        
        if operation == 'request':
            request_data = event.get('request', {})
            request_data['request_id'] = str(uuid.uuid4())
            request_data['created_at'] = datetime.now().isoformat()
            request_data['status'] = 'PENDING'
            
            table.put_item(Item=request_data)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Leave request submitted successfully',
                    'request_id': request_data['request_id']
                })
            }
            
        elif operation == 'get':
            request_id = event.get('request_id')
            response = table.get_item(Key={'request_id': request_id})
            return {
                'statusCode': 200,
                'body': json.dumps(response.get('Item'))
            }
            
        elif operation == 'list':
            employee_id = event.get('employee_id')
            response = table.scan()
            requests = response.get('Items', [])
            
            if employee_id:
                requests = [r for r in requests if r.get('employee_id') == employee_id]
                
            return {
                'statusCode': 200,
                'body': json.dumps(requests)
            }
            
        elif operation == 'update_status':
            request_id = event.get('request_id')
            new_status = event.get('status')
            
            table.update_item(
                Key={'request_id': request_id},
                UpdateExpression='SET #status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': new_status}
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Leave request status updated successfully'})
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
