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
python infrastructure/infrastructure.py

echo "Setup completed successfully!"
echo "To start the application, run: python src/web/app.py"
