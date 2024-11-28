import json
import boto3
import uuid
from datetime import datetime

def lambda_handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('Employees')
    
    try:
        operation = event.get('operation')
        
        if operation == 'create':
            employee_data = event.get('employee', {})
            employee_data['employee_id'] = str(uuid.uuid4())
            employee_data['created_at'] = datetime.now().isoformat()
            
            table.put_item(Item=employee_data)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Employee created successfully',
                    'employee_id': employee_data['employee_id']
                })
            }
            
        elif operation == 'get':
            employee_id = event.get('employee_id')
            response = table.get_item(Key={'employee_id': employee_id})
            return {
                'statusCode': 200,
                'body': json.dumps(response.get('Item'))
            }
            
        elif operation == 'list':
            response = table.scan()
            return {
                'statusCode': 200,
                'body': json.dumps(response.get('Items', []))
            }
            
        elif operation == 'update':
            employee_id = event.get('employee_id')
            updates = event.get('updates', {})
            
            update_expression = 'SET '
            expression_values = {}
            
            for key, value in updates.items():
                update_expression += f'#{key} = :{key}, '
                expression_values[f':{key}'] = value
            
            table.update_item(
                Key={'employee_id': employee_id},
                UpdateExpression=update_expression[:-2],
                ExpressionAttributeValues=expression_values,
                ExpressionAttributeNames={f'#{k}': k for k in updates.keys()}
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Employee updated successfully'})
            }
            
        elif operation == 'delete':
            employee_id = event.get('employee_id')
            table.delete_item(Key={'employee_id': employee_id})
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Employee deleted successfully'})
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
