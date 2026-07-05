import os
keys = [k for k in os.environ.keys() if 'proxy' in k.lower()]
for k in sorted(keys):
    print(f"{k}={os.environ.get(k)}")
