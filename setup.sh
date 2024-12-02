#!/bin/bash

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Run infrastructure setup
if python infrastructure/infrastructure.py; then
    echo "Setup completed successfully!"
    echo "Starting the application..."
    python src/web/app.py
else
    echo "Setup failed. Please check the errors above."
    exit 1
fi
