from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import boto3
import json
import os
from functools import wraps
from werkzeug.utils import secure_filename
import requests
from datetime import datetime, date, timedelta
import uuid
from dotenv import load_dotenv
import bcrypt

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION'))
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION'))

# Context processor for date
@app.context_processor
def inject_today():
    return {'today': date.today()}

def get_upcoming_holidays():
    today = date.today()
    holidays = [
        {'name': 'Christmas Day', 'date': date(today.year, 12, 25)},
        {'name': "New Year's Day", 'date': date(today.year + 1, 1, 1)}
    ]
    
    return [{
        'name': holiday['name'],
        'date': holiday['date'].strftime('%B %d, %Y'),
        'days_left': (holiday['date'] - today).days
    } for holiday in holidays if holiday['date'] >= today]

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin', False):
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            table = dynamodb.Table('Employees')
            response = table.get_item(Key={'email': email})
            
            if 'Item' in response:
                employee = response['Item']
                if check_password(password, employee['password']):
                    session['user_id'] = employee['employee_id']
                    session['user_name'] = employee['name']
                    session['email'] = employee['email']
                    session['is_admin'] = employee.get('is_admin', False)
                    flash('Login successful!', 'success')
                    return redirect(url_for('dashboard'))
            
            flash('Invalid email or password', 'error')
        except Exception as e:
            flash(f'Login error: {str(e)}', 'error')
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        stats = {}
        
        # Get document count
        doc_table = dynamodb.Table('Documents')
        doc_response = doc_table.scan(
            FilterExpression='employee_id = :eid',
            ExpressionAttributeValues={':eid': session['user_id']}
        ) if not session.get('is_admin') else doc_table.scan()
        stats['documents_count'] = len(doc_response.get('Items', []))
        
        # Get employee count (admin only)
        if session.get('is_admin'):
            emp_table = dynamodb.Table('Employees')
            emp_response = emp_table.scan()
            stats['employees_count'] = len(emp_response.get('Items', []))
        
        # Calculate leave balance
        leave_table = dynamodb.Table('LeaveRequests')
        leave_response = leave_table.scan(
            FilterExpression='employee_id = :eid',
            ExpressionAttributeValues={':eid': session['user_id']}
        )
        leave_requests = leave_response.get('Items', [])
        
        approved_leaves = sum(
            (datetime.strptime(req['end_date'], '%Y-%m-%d') - 
             datetime.strptime(req['start_date'], '%Y-%m-%d')).days + 1
            for req in leave_requests 
            if req['status'] == 'APPROVED'
        )
        stats['leave_balance'] = 30 - approved_leaves
        
        # Get upcoming holidays
        stats['upcoming_holidays'] = get_upcoming_holidays()
        
        return render_template('dashboard.html',
                           user_name=session.get('user_name'),
                           is_admin=session.get('is_admin', False),
                           stats=stats)
                           
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('dashboard.html',
                           user_name=session.get('user_name'),
                           is_admin=session.get('is_admin', False))

@app.route('/employees', methods=['GET', 'POST'])
@login_required
@admin_required
def employees():
    table = dynamodb.Table('Employees')
    
    if request.method == 'POST':
        try:
            email = request.form['email']
            
            # Check if email exists
            response = table.get_item(Key={'email': email})
            if 'Item' in response:
                flash('Email already exists', 'error')
                return redirect(url_for('employees'))
            
            employee_data = {
                'email': email,
                'employee_id': str(uuid.uuid4()),
                'name': request.form['name'],
                'password': hash_password(request.form['password']).decode('utf-8'),
                'department': request.form['department'],
                'position': request.form['position'],
                'is_admin': request.form.get('is_admin') == 'on',
                'created_at': datetime.now().isoformat(),
                'created_by': session['email']
            }
            
            table.put_item(Item=employee_data)
            flash('Employee added successfully', 'success')
        except Exception as e:
            flash(f'Error adding employee: {str(e)}', 'error')
        
        return redirect(url_for('employees'))
    
    try:
        response = table.scan()
        employees_list = response.get('Items', [])
        for emp in employees_list:
            emp.pop('password', None)
    except Exception as e:
        flash(f'Error retrieving employees: {str(e)}', 'error')
        employees_list = []
    
    return render_template('employees/list.html',
                         employees=employees_list,
                         is_admin=session.get('is_admin', False))

@app.route('/leave-requests', methods=['GET', 'POST'])
@login_required
def leave_requests():
    table = dynamodb.Table('LeaveRequests')
    
    if request.method == 'POST':
        if session.get('is_admin'):
            flash('Admins cannot submit leave requests', 'error')
            return redirect(url_for('leave_requests'))
            
        try:
            leave_data = {
                'request_id': str(uuid.uuid4()),
                'employee_id': session['user_id'],
                'employee_name': session['user_name'],
                'start_date': request.form['start_date'],
                'end_date': request.form['end_date'],
                'reason': request.form['reason'],
                'status': 'PENDING',
                'created_at': datetime.now().isoformat()
            }
            
            table.put_item(Item=leave_data)
            flash('Leave request submitted successfully', 'success')
        except Exception as e:
            flash(f'Error submitting leave request: {str(e)}', 'error')
        
        return redirect(url_for('leave_requests'))
    
    try:
        if session.get('is_admin'):
            response = table.scan()
        else:
            response = table.scan(
                FilterExpression='employee_id = :eid',
                ExpressionAttributeValues={':eid': session['user_id']}
            )
        requests_list = response.get('Items', [])
    except Exception as e:
        flash(f'Error retrieving leave requests: {str(e)}', 'error')
        requests_list = []
    
    return render_template('leave/list.html',
                         requests=requests_list,
                         is_admin=session.get('is_admin', False))

@app.route('/leave-requests/approve/<request_id>', methods=['POST'])
@login_required
@admin_required
def approve_leave(request_id):
    try:
        table = dynamodb.Table('LeaveRequests')
        table.update_item(
            Key={'request_id': request_id},
            UpdateExpression='SET #status = :status, updated_at = :updated_at, approved_by = :approved_by',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'APPROVED',
                ':updated_at': datetime.now().isoformat(),
                ':approved_by': session['email']
            }
        )
        flash('Leave request approved successfully', 'success')
        return jsonify({'status': 'success'})
    except Exception as e:
        flash(f'Error approving leave request: {str(e)}', 'error')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/leave-requests/reject/<request_id>', methods=['POST'])
@login_required
@admin_required
def reject_leave(request_id):
    try:
        table = dynamodb.Table('LeaveRequests')
        table.update_item(
            Key={'request_id': request_id},
            UpdateExpression='SET #status = :status, updated_at = :updated_at, rejected_by = :rejected_by',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'REJECTED',
                ':updated_at': datetime.now().isoformat(),
                ':rejected_by': session['email']
            }
        )
        flash('Leave request rejected successfully', 'success')
        return jsonify({'status': 'success'})
    except Exception as e:
        flash(f'Error rejecting leave request: {str(e)}', 'error')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/documents', methods=['GET', 'POST'])
@login_required
def documents():
    table = dynamodb.Table('Documents')
    
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('No file selected', 'error')
                return redirect(request.url)
            
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.url)
            
            if file:
                filename = secure_filename(file.filename)
                document_id = str(uuid.uuid4())
                s3_key = f"{session['user_id']}/{document_id}/{filename}"
                
                # Upload to S3
                s3_client.upload_fileobj(
                    file,
                    os.getenv('S3_BUCKET_NAME'),
                    s3_key,
                    ExtraArgs={'ContentType': file.content_type}
                )
                
                # Store metadata
                document_data = {
                    'document_id': document_id,
                    'employee_id': session['user_id'],
                    'employee_name': session['user_name'],
                    'filename': filename,
                    'description': request.form.get('description', ''),
                    's3_key': s3_key,
                    'created_at': datetime.now().isoformat()
                }
                
                table.put_item(Item=document_data)
                flash('Document uploaded successfully', 'success')
                
        except Exception as e:
            flash(f'Error uploading document: {str(e)}', 'error')
            
        return redirect(url_for('documents'))
    
    try:
        if session.get('is_admin'):
            response = table.scan()
        else:
            response = table.scan(
                FilterExpression='employee_id = :eid',
                ExpressionAttributeValues={':eid': session['user_id']}
            )
        documents_list = response.get('Items', [])
        
        # Generate download URLs
        for doc in documents_list:
            doc['download_url'] = s3_client.generate_presigned_url('get_object',
                Params={
                    'Bucket': os.getenv('S3_BUCKET_NAME'),
                    'Key': doc['s3_key']
                },
                ExpiresIn=3600
            )
    except Exception as e:
        flash(f'Error retrieving documents: {str(e)}', 'error')
        documents_list = []
    
    return render_template('documents/list.html',
                         documents=documents_list,
                         is_admin=session.get('is_admin', False))

@app.route('/documents/delete/<document_id>', methods=['POST'])
@login_required
def delete_document(document_id):
    try:
        table = dynamodb.Table('Documents')
        response = table.get_item(Key={'document_id': document_id})
        
        if 'Item' in response:
            document = response['Item']
            
            if document['employee_id'] == session['user_id'] or session.get('is_admin'):
                # Delete from S3
                s3_client.delete_object(
                    Bucket=os.getenv('S3_BUCKET_NAME'),
                    Key=document['s3_key']
                )
                
                # Delete from DynamoDB
                table.delete_item(Key={'document_id': document_id})
                
                flash('Document deleted successfully', 'success')
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
        
        return jsonify({'status': 'error', 'message': 'Document not found'}), 404
        
    except Exception as e:
        flash(f'Error deleting document: {str(e)}', 'error')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.template_filter('format_date')
def format_date(date_string):
    try:
        date_obj = datetime.fromisoformat(date_string)
        return date_obj.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return date_string

if __name__ == '__main__':
    app.run(debug=True)
