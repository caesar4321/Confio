#!/bin/bash

# Activate virtual environment
source myvenv/bin/activate

# Set environment variables
export PYTHONPATH=/Users/julianmoon/Confio:$PYTHONPATH
export DJANGO_SETTINGS_MODULE=config.settings

# Execute Django command
python "$@" 