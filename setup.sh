#!/bin/bash

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Create necessary directories
mkdir -p src/web/templates/{employees,leave,documents}
mkdir -p src/web/static/{css,js}
mkdir -p infrastructure

# Create base and login templates (previous content remains the same)
cat > src/web/templates/leave/list.html << 'EOF'
{% extends "base.html" %}
{% block title %}Leave Requests{% endblock %}
{% block content %}
<div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold">Leave Requests</h2>
    <button onclick="document.getElementById('createLeaveModal').classList.remove('hidden')" 
            class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
        Request Leave
    </button>
</div>

<div class="bg-white rounded-lg shadow-md overflow-hidden">
    <table class="min-w-full">
        <thead>
            <tr class="bg-gray-100">
                <th class="px-6 py-3 text-left text-gray-700">Start Date</th>
                <th class="px-6 py-3 text-left text-gray-700">End Date</th>
                <th class="px-6 py-3 text-left text-gray-700">Reason</th>
                <th class="px-6 py-3 text-left text-gray-700">Status</th>
                <th class="px-6 py-3 text-left text-gray-700">Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for request in requests %}
            <tr class="border-t">
                <td class="px-6 py-4">{{ request.start_date }}</td>
                <td class="px-6 py-4">{{ request.end_date }}</td>
                <td class="px-6 py-4">{{ request.reason }}</td>
                <td class="px-6 py-4">
                    <span class="px-2 py-1 rounded text-sm
                        {% if request.status == 'APPROVED' %}bg-green-100 text-green-800
                        {% elif request.status == 'REJECTED' %}bg-red-100 text-red-800
                        {% else %}bg-yellow-100 text-yellow-800{% endif %}">
                        {{ request.status }}
                    </span>
                </td>
                <td class="px-6 py-4">
                    {% if request.status == 'PENDING' %}
                    <button onclick="cancelRequest('{{ request.request_id }}')"
                            class="text-red-600 hover:text-red-800">Cancel</button>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<!-- Create Leave Request Modal -->
<div id="createLeaveModal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full">
    <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
        <div class="mt-3">
            <h3 class="text-lg font-medium leading-6 text-gray-900 mb-4">Request Leave</h3>
            <form method="POST">
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Start Date</label>
                    <input type="date" name="start_date" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">End Date</label>
                    <input type="date" name="end_date" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Reason</label>
                    <textarea name="reason" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" rows="3" required></textarea>
                </div>
                <div class="flex justify-end space-x-4">
                    <button type="button" onclick="document.getElementById('createLeaveModal').classList.add('hidden')"
                            class="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded">
                        Cancel
                    </button>
                    <button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                        Submit
                    </button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
EOF

cat > src/web/templates/documents/list.html << 'EOF'
{% extends "base.html" %}
{% block title %}Documents{% endblock %}
{% block content %}
<div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold">Documents</h2>
    <button onclick="document.getElementById('uploadDocumentModal').classList.remove('hidden')" 
            class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
        Upload Document
    </button>
</div>

<div class="bg-white rounded-lg shadow-md overflow-hidden">
    <table class="min-w-full">
        <thead>
            <tr class="bg-gray-100">
                <th class="px-6 py-3 text-left text-gray-700">Filename</th>
                <th class="px-6 py-3 text-left text-gray-700">Description</th>
                <th class="px-6 py-3 text-left text-gray-700">Upload Date</th>
                <th class="px-6 py-3 text-left text-gray-700">Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for document in documents %}
            <tr class="border-t">
                <td class="px-6 py-4">{{ document.filename }}</td>
                <td class="px-6 py-4">{{ document.description }}</td>
                <td class="px-6 py-4">{{ document.created_at }}</td>
                <td class="px-6 py-4">
                    <a href="{{ document.download_url }}" class="text-blue-600 hover:text-blue-800 mr-2">Download</a>
                    <button onclick="deleteDocument('{{ document.document_id }}')"
                            class="text-red-600 hover:text-red-800">Delete</button>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<!-- Upload Document Modal -->
<div id="uploadDocumentModal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full">
    <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
        <div class="mt-3">
            <h3 class="text-lg font-medium leading-6 text-gray-900 mb-4">Upload Document</h3>
            <form method="POST" enctype="multipart/form-data">
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">File</label>
                    <input type="file" name="file" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Description</label>
                    <textarea name="description" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" rows="3"></textarea>
                </div>
                <div class="flex justify-end space-x-4">
                    <button type="button" onclick="document.getElementById('uploadDocumentModal').classList.add('hidden')"
                            class="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded">
                        Cancel
                    </button>
                    <button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                        Upload
                    </button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
EOF

cat > src/web/templates/employees/list.html << 'EOF'
{% extends "base.html" %}
{% block title %}Employees{% endblock %}
{% block content %}
<div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold">Employees</h2>
    <button onclick="document.getElementById('createEmployeeModal').classList.remove('hidden')" 
            class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
        Add Employee
    </button>
</div>

<div class="bg-white rounded-lg shadow-md overflow-hidden">
    <table class="min-w-full">
        <thead>
            <tr class="bg-gray-100">
                <th class="px-6 py-3 text-left text-gray-700">Name</th>
                <th class="px-6 py-3 text-left text-gray-700">Email</th>
                <th class="px-6 py-3 text-left text-gray-700">Department</th>
                <th class="px-6 py-3 text-left text-gray-700">Position</th>
                <th class="px-6 py-3 text-left text-gray-700">Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for employee in employees %}
            <tr class="border-t">
                <td class="px-6 py-4">{{ employee.name }}</td>
                <td class="px-6 py-4">{{ employee.email }}</td>
                <td class="px-6 py-4">{{ employee.department }}</td>
                <td class="px-6 py-4">{{ employee.position }}</td>
                <td class="px-6 py-4">
                    <button class="text-blue-600 hover:text-blue-800 mr-2">Edit</button>
                    <button class="text-red-600 hover:text-red-800">Delete</button>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<!-- Create Employee Modal -->
<div id="createEmployeeModal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full">
    <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
        <div class="mt-3">
            <h3 class="text-lg font-medium leading-6 text-gray-900 mb-4">Create New Employee</h3>
            <form method="POST">
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Name</label>
                    <input type="text" name="name" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Email</label>
                    <input type="email" name="email" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Department</label>
                    <input type="text" name="department" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700 text-sm font-bold mb-2">Position</label>
                    <input type="text" name="position" class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700" required>
                </div>
                <div class="flex justify-end space-x-4">
                    <button type="button" onclick="document.getElementById('createEmployeeModal').classList.add('hidden')"
                            class="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded">
                        Cancel
                    </button>
                    <button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                        Create
                    </button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
EOF

# Run infrastructure setup
python infrastructure/infrastructure.py

echo "Setup completed successfully!"
echo "To start the application, run: python src/web/app.py"