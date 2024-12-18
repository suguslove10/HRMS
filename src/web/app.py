from flask import (
    Flask, 
    render_template, 
    request, 
    jsonify, 
    session, 
    redirect, 
    url_for, 
    flash, 
    send_file, 
    make_response
)
import io
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
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION'))
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION'))

# Template Filters
@app.template_filter('format_date')
def format_date(date_string):
    try:
        date_obj = datetime.fromisoformat(date_string)
        return date_obj.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return date_string

@app.template_filter('time_ago')
def time_ago(date_string):
    """Convert a datetime string to a 'time ago' string (e.g., '2 hours ago')"""
    try:
        # Parse the ISO format datetime string
        date_obj = datetime.fromisoformat(date_string)
        now = datetime.now()
        diff = now - date_obj

        # Calculate the time difference
        seconds = diff.total_seconds()
        minutes = seconds // 60
        hours = minutes // 60
        days = diff.days

        # Return appropriate string based on time difference
        if days > 365:
            years = days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        if days > 30:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        if days > 0:
            return f"{days} day{'s' if days != 1 else ''} ago"
        if hours > 0:
            return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
        if minutes > 0:
            return f"{int(minutes)} minute{'s' if int(minutes) != 1 else ''} ago"
        return "just now"
    except Exception as e:
        print(f"Error in time_ago filter: {e}")
        return date_string

# Context processor for date
@app.context_processor
def inject_today():
    return {'today': date.today()}

def get_upcoming_holidays():
    today = date.today()
    current_year = today.year
    next_year = current_year + 1
    
    holidays = [
        # Current Year Holidays
        {'name': 'Republic Day', 'date': date(current_year, 1, 26)},
        {'name': 'Good Friday', 'date': date(current_year, 3, 29)},
        {'name': 'Eid al-Fitr', 'date': date(current_year, 4, 11)},
        {'name': 'Independence Day', 'date': date(current_year, 8, 15)},
        {'name': 'Gandhi Jayanti', 'date': date(current_year, 10, 2)},
        {'name': 'Diwali', 'date': date(current_year, 11, 1)},
        {'name': 'Christmas Day', 'date': date(current_year, 12, 25)},
        # Next Year Holidays
        {'name': "New Year's Day", 'date': date(next_year, 1, 1)},
    ]
    
    upcoming = []
    for holiday in holidays:
        days_left = (holiday['date'] - today).days
        if days_left >= 0:
            upcoming.append({
                'name': holiday['name'],
                'date': holiday['date'].strftime('%B %d, %Y'),
                'days_left': days_left
            })
    
    return sorted(upcoming, key=lambda x: x['days_left'])[:4]

def get_employee_stats():
    try:
        table = dynamodb.Table('Employees')
        response = table.scan()
        employees = response.get('Items', [])
        
        stats = {
            'total_count': len(employees),
            'departments': {},
            'roles': {},
            'admin_count': 0
        }
        
        for emp in employees:
            dept = emp.get('department', 'Other')
            stats['departments'][dept] = stats['departments'].get(dept, 0) + 1
            
            role = emp.get('role', 'employee')
            stats['roles'][role] = stats['roles'].get(role, 0) + 1
            
            if emp.get('role') in ['admin', 'super_admin']:
                stats['admin_count'] += 1
        
        return stats
    except Exception as e:
        print(f"Error getting employee stats: {e}")
        return None

def get_leave_balance(employee_id):
    try:
        table = dynamodb.Table('LeaveRequests')
        response = table.scan(
            FilterExpression='employee_id = :eid AND #status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':eid': employee_id,
                ':status': 'APPROVED'
            }
        )
        
        total_days_taken = sum(
            (datetime.strptime(req['end_date'], '%Y-%m-%d') - 
             datetime.strptime(req['start_date'], '%Y-%m-%d')).days + 1
            for req in response.get('Items', [])
        )
        
        return 30 - total_days_taken
    except Exception as e:
        print(f"Error calculating leave balance: {e}")
        return 0

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# Decorators
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
        if session.get('role') not in ['admin', 'super_admin']:
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'super_admin':
            flash('Super Admin access required', 'error')
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
                    session['department'] = employee.get('department', 'General')
                    session['position'] = employee.get('position', 'Employee')
                    # Update role handling
                    if employee.get('is_super_admin'):
                        session['role'] = 'super_admin'
                    elif employee.get('is_admin'):
                        session['role'] = 'admin'
                    else:
                        session['role'] = 'employee'
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
        
        # Get leave balance
        stats['leave_balance'] = get_leave_balance(session['user_id'])
        
        # Get recent activity
        activity = []
        
        # Get recent leave requests
        leave_table = dynamodb.Table('LeaveRequests')
        leave_response = leave_table.scan(
            FilterExpression='employee_id = :eid',
            ExpressionAttributeValues={':eid': session['user_id']}
        )
        for item in leave_response.get('Items', []):
            activity.append({
                'type': 'leave_request',
                'status': item['status'],
                'date': item['created_at'],
                'description': f"Leave request from {item['start_date']} to {item['end_date']}"
            })
            
        # Get recent document uploads
        for doc in doc_response.get('Items', []):
            activity.append({
                'type': 'document',
                'date': doc['created_at'],
                'description': f"Uploaded document: {doc['filename']}"
            })
            
        # Sort activity by date
        activity.sort(key=lambda x: x['date'], reverse=True)
        stats['recent_activity'] = activity[:5]  # Get 5 most recent activities
        
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
            
            # Only super_admin can create other admins
            if request.form.get('is_admin') == 'on' and session.get('role') != 'super_admin':
                flash('Only Super Admins can create admin accounts', 'error')
                return redirect(url_for('employees'))

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
                'is_super_admin': request.form.get('is_super_admin') == 'on' and session.get('role') == 'super_admin',
                'created_at': datetime.now().isoformat(),
                'created_by': session['email']
            }
            
            table.put_item(Item=employee_data)
            flash('Employee added successfully', 'success')
        except Exception as e:
            flash(f'Error adding employee: {str(e)}', 'error')
        
    # Retrieve all employees from DynamoDB
    try:
        response = table.scan()
        employees_list = response.get('Items', [])
        
        # Process each employee to set their role
        for emp in employees_list:
            if emp.get('is_super_admin'):
                emp['role'] = 'Super Admin'
            elif emp.get('is_admin'):
                emp['role'] = 'Admin'
            else:
                emp['role'] = 'Employee'
                
        # Sort employees: Super Admins first, then Admins, then regular employees
        employees_list.sort(key=lambda x: (
            0 if x.get('is_super_admin') else (1 if x.get('is_admin') else 2),
            x.get('name', '').lower()
        ))
        
    except Exception as e:
        flash(f'Error retrieving employees: {str(e)}', 'error')
        employees_list = []
    
    return render_template('employees/list.html', 
                         employees=employees_list, 
                         is_super_admin=session.get('role') == 'super_admin')

@app.route('/employees/edit/<email>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_employee(email):
    table = dynamodb.Table('Employees')
    
    if request.method == 'POST':
        try:
            update_expr = ['SET']
            expr_values = {}
            expr_names = {}
            
            fields = {
                'name': '#n',
                'department': '#d',
                'position': '#p'
            }
            
            for field, placeholder in fields.items():
                if request.form.get(field):
                    update_expr.append(f'{placeholder} = :{field}')
                    expr_values[f':{field}'] = request.form[field]
                    expr_names[placeholder] = field
            
            # Handle admin status updates
            if session.get('role') == 'super_admin':
                is_admin = request.form.get('is_admin') == 'on'
                is_super_admin = request.form.get('is_super_admin') == 'on'
                
                update_expr.append('#ia = :is_admin')
                update_expr.append('#isa = :is_super_admin')
                expr_values[':is_admin'] = is_admin
                expr_values[':is_super_admin'] = is_super_admin
                expr_names['#ia'] = 'is_admin'
                expr_names['#isa'] = 'is_super_admin'
            
            # Update password if provided
            if request.form.get('password'):
                hashed_password = bcrypt.hashpw(
                    request.form['password'].encode('utf-8'), 
                    bcrypt.gensalt()
                ).decode('utf-8')
                update_expr.append('#pw = :password')
                expr_values[':password'] = hashed_password
                expr_names['#pw'] = 'password'
            
            update_expression = ' , '.join(update_expr)
            
            table.update_item(
                Key={'email': email},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names
            )
            
            flash('Employee updated successfully', 'success')
            return jsonify({'status': 'success'})
            
        except Exception as e:
            flash(f'Error updating employee: {str(e)}', 'error')
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    try:
        response = table.get_item(Key={'email': email})
        if 'Item' in response:
            return jsonify({
                'status': 'success',
                'employee': {
                    'name': response['Item'].get('name', ''),
                    'email': response['Item'].get('email', ''),
                    'department': response['Item'].get('department', ''),
                    'position': response['Item'].get('position', ''),
                    'is_admin': response['Item'].get('is_admin', False),
                    'is_super_admin': response['Item'].get('is_super_admin', False)
                }
            })
        return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees/delete/<email>', methods=['POST'])
@login_required
@admin_required
def delete_employee(email):
    if session.get('role') != 'super_admin' and email in ['superadmin@hrms.com', 'admin@hrms.com']:
        return jsonify({'status': 'error', 'message': 'Cannot delete system administrators'}), 403
        
    try:
        table = dynamodb.Table('Employees')
        response = table.get_item(Key={'email': email})
        
        if 'Item' not in response:
            return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            
        # Only super admin can delete admins
        if response['Item'].get('is_admin') and session.get('role') != 'super_admin':
            return jsonify({'status': 'error', 'message': 'Only super admin can delete administrators'}), 403
            
        table.delete_item(Key={'email': email})
        flash('Employee deleted successfully', 'success')
        return jsonify({'status': 'success'})
        
    except Exception as e:
        flash(f'Error deleting employee: {str(e)}', 'error')
        return jsonify({'status': 'error', 'message': str(e)}), 500
        
    # Retrieve all employees from DynamoDB
    try:
        response = table.scan()
        employees_list = response.get('Items', [])
    except Exception as e:
        flash(f'Error retrieving employees: {str(e)}', 'error')
        employees_list = []
    
    return render_template('employees/list.html', employees=employees_list)

@app.route('/leave-requests', methods=['GET', 'POST'])
@login_required
def leave_requests():
    if session.get('is_admin'):
        return redirect(url_for('admin_leave_requests'))
        
    table = dynamodb.Table('LeaveRequests')
    
    if request.method == 'POST':
        try:
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
            days_count = (end_date - start_date).days + 1
            
            current_balance = get_leave_balance(session['user_id'])
            if days_count > current_balance:
                flash(f'Insufficient leave balance. You have {current_balance} days remaining.', 'error')
                return redirect(url_for('leave_requests'))
            
            leave_data = {
                'request_id': str(uuid.uuid4()),
                'employee_id': session['user_id'],
                'employee_name': session['user_name'],
                'start_date': request.form['start_date'],
                'end_date': request.form['end_date'],
                'days_requested': days_count,
                'reason': request.form['reason'],
                'status': 'PENDING_ADMIN' if session.get('is_admin') else 'PENDING',
                'created_at': datetime.now().isoformat()
            }
            
            table.put_item(Item=leave_data)
            flash('Leave request submitted successfully', 'success')
        except Exception as e:
            flash(f'Error submitting leave request: {str(e)}', 'error')
        
        return redirect(url_for('leave_requests'))
    
    try:
        response = table.scan(
            FilterExpression='employee_id = :eid',
            ExpressionAttributeValues={':eid': session['user_id']}
        )
        requests_list = response.get('Items', [])
        requests_list.sort(key=lambda x: x['created_at'], reverse=True)
    except Exception as e:
        flash(f'Error retrieving leave requests: {str(e)}', 'error')
        requests_list = []
    
    return render_template('leave/list.html',
                         requests=requests_list,
                         leave_balance=get_leave_balance(session['user_id']))



@app.route('/admin/leave-requests', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_leave_requests():
    from flask import request
    table = dynamodb.Table('LeaveRequests')
    employees_table = dynamodb.Table('Employees')

    try:
        # Get all employees first
        emp_response = employees_table.scan()
        employees_dict = {}
        for emp in emp_response.get('Items', []):
            # Store by both email and employee_id
            employees_dict[emp.get('email')] = emp
            employees_dict[emp.get('employee_id', '')] = emp

        # Get leave requests
        response = table.scan()
        leave_requests = response.get('Items', [])

        pending_count = 0
        approved_count = 0

        # Process each leave request
        for leave_req in leave_requests:
            employee_id = leave_req.get('employee_id')
            employee = employees_dict.get(employee_id, {})

            # Add employee details to request object
            leave_req['employee_name'] = employee.get('name', leave_req.get('employee_name', 'Unknown'))
            leave_req['department'] = employee.get('department', 'Department Not Available')
            leave_req['position'] = employee.get('position', 'Position Not Available')
            leave_req['employee_email'] = employee.get('email', employee_id)

            # Calculate days
            try:
                start_date = datetime.strptime(leave_req['start_date'], '%Y-%m-%d')
                end_date = datetime.strptime(leave_req['end_date'], '%Y-%m-%d')
                days = (end_date - start_date).days + 1
                leave_req['duration'] = f"{days} days"
            except Exception as e:
                print(f"Error calculating duration: {e}")
                leave_req['duration'] = "Duration not available"

            # Update counts
            if leave_req.get('status') == 'PENDING':
                pending_count += 1
            elif leave_req.get('status') == 'APPROVED':
                approved_count += 1

        # Sort requests
        leave_requests.sort(key=lambda x: (
            0 if x.get('status') == 'PENDING' else 1,
            x.get('created_at', ''),
        ), reverse=True)

        leave_balance = get_leave_balance(session.get('user_id', ''))

        return render_template('admin/leave_requests.html',
                             requests=leave_requests,
                             pending_count=pending_count,
                             approved_count=approved_count,
                             leave_balance=leave_balance)

    except Exception as e:
        print(f"Error in admin_leave_requests: {e}")
        flash('Error retrieving leave requests. Please try again.', 'error')
        return render_template('admin/leave_requests.html',
                             requests=[],
                             pending_count=0,
                             approved_count=0,
                             leave_balance=0)

@app.route('/leave-requests/approve/<request_id>', methods=['POST'])
@login_required
@admin_required
def approve_leave(request_id):
    try:
        table = dynamodb.Table('LeaveRequests')
        
        # Get the leave request
        response = table.get_item(Key={'request_id': request_id})
        if 'Item' not in response:
            return jsonify({'status': 'error', 'message': 'Leave request not found'}), 404
            
        leave_request = response['Item']
        
        # Check if admin can approve
        if session.get('role') != 'super_admin':
            emp_table = dynamodb.Table('Employees')
            emp_response = emp_table.get_item(
                Key={'email': leave_request['employee_id']}  # Note: Using email as the key
            )
            if 'Item' in emp_response and emp_response['Item'].get('is_admin'):
                return jsonify({'status': 'error', 'message': 'Only Super Admin can approve admin leave requests'}), 403
        
        # Update the leave request status
        table.update_item(
            Key={'request_id': request_id},
            UpdateExpression='SET #status = :status, updated_at = :updated_at, approved_by = :approved_by',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'APPROVED',
                ':updated_at': datetime.now().isoformat(),
                ':approved_by': session.get('email')
            },
            ReturnValues='ALL_NEW'  # This will return the updated item
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
                
                # Upload to S3 with server-side encryption
                s3_client.upload_fileobj(
                    file,
                    os.getenv('S3_BUCKET_NAME'),
                    s3_key,
                    ExtraArgs={
                        'ServerSideEncryption': 'AES256',
                        'ContentType': file.content_type
                    }
                )
                
                document_data = {
                    'document_id': document_id,
                    'employee_id': session['user_id'],
                    'employee_name': session['user_name'],
                    'filename': filename,
                    'description': request.form.get('description', ''),
                    's3_key': s3_key,
                    'created_at': datetime.now().isoformat(),
                    'is_public': request.form.get('is_public') == 'on'
                }
                
                table.put_item(Item=document_data)
                flash('Document uploaded successfully', 'success')
                
        except Exception as e:
            flash(f'Error uploading document: {str(e)}', 'error')
            
        return redirect(url_for('documents'))
    
    try:
        if session.get('is_admin'):
            # Admins can see all documents
            response = table.scan()
        else:
            # Regular employees see their own documents and public documents
            response = table.scan(
                FilterExpression='employee_id = :eid OR is_public = :pub',
                ExpressionAttributeValues={
                    ':eid': session['user_id'],
                    ':pub': True
                }
            )
        documents_list = response.get('Items', [])
        
        # Generate download URLs for each document
        for doc in documents_list:
            try:
                doc['download_url'] = url_for('download_document', document_id=doc['document_id'])
            except Exception as e:
                print(f"Error generating URL for document {doc['document_id']}: {e}")
                doc['download_url'] = '#'
            
    except Exception as e:
        flash(f'Error retrieving documents: {str(e)}', 'error')
        documents_list = []
    
    return render_template('documents/list.html',
                         documents=documents_list,
                         is_admin=session.get('is_admin', False))

@app.route('/documents/download/<document_id>')
@login_required
def download_document(document_id):
    try:
        # Print debugging information (remove in production)
        print("AWS Region:", os.getenv('AWS_REGION'))
        print("Bucket Name:", os.getenv('S3_BUCKET_NAME'))
        print("Access Key exists:", bool(os.getenv('AWS_ACCESS_KEY_ID')))
        print("Secret Key exists:", bool(os.getenv('AWS_SECRET_ACCESS_KEY')))

        # Get document details from DynamoDB
        table = dynamodb.Table('Documents')
        response = table.get_item(Key={'document_id': document_id})
        
        if 'Item' not in response:
            flash('Document not found', 'error')
            return redirect(url_for('documents'))
            
        document = response['Item']
        
        # Check if user has permission to download
        if not (document['employee_id'] == session['user_id'] or 
                session.get('is_admin') or 
                document.get('is_public')):
            flash('Permission denied', 'error')
            return redirect(url_for('documents'))

        try:
            # Get the file from S3
            s3_response = s3_client.get_object(
                Bucket=os.getenv('S3_BUCKET_NAME'),
                Key=document['s3_key']
            )
            
            # Stream the file directly to the user
            return send_file(
                s3_response['Body'],
                download_name=document['filename'],
                as_attachment=True,
                mimetype=s3_response['ContentType']
            )
            
        except Exception as e:
            print(f"S3 Error: {str(e)}")
            flash('Error accessing document from storage', 'error')
            return redirect(url_for('documents'))
            
    except Exception as e:
        print(f"General Error: {str(e)}")
        flash('Error accessing document', 'error')
        return redirect(url_for('documents'))

@app.route('/documents/delete/<document_id>', methods=['POST'])
@login_required
def delete_document(document_id):
    try:
        table = dynamodb.Table('Documents')
        response = table.get_item(Key={'document_id': document_id})
        
        if 'Item' in response:
            document = response['Item']
            
            # Check if user has permission to delete
            if document['employee_id'] == session['user_id'] or session.get('is_admin'):
                # Delete from S3
                try:
                    s3_client.delete_object(
                        Bucket=os.getenv('S3_BUCKET_NAME'),
                        Key=document['s3_key']
                    )
                except Exception as e:
                    print(f"Error deleting from S3: {e}")
                
                # Delete from DynamoDB
                table.delete_item(Key={'document_id': document_id})
                
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
        
        return jsonify({'status': 'error', 'message': 'Document not found'}), 404
        
    except Exception as e:
        print(f"Error in delete_document: {e}")
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
