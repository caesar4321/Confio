import sys
print("Python path:")
for path in sys.path:
    print(f"  {path}")

try:
    import django
    print(f"\nDjango version: {django.__version__}")
except ImportError as e:
    print(f"\nError importing Django: {e}") 