import os
import sys

print("Python version:", sys.version)
print("\nPython path:")
for path in sys.path:
    print(path)

print("\nEnvironment variables:")
for key, value in os.environ.items():
    if 'PYTHON' in key or 'DJANGO' in key:
        print(f"{key}: {value}")

try:
    import django
    print("\nDjango version:", django.get_version())
except ImportError:
    print("\nDjango is not installed") 