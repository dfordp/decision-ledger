import requests

r = requests.get('http://localhost:8000/api/vehicles')
data = r.json()

print(f'Found {len(data)} vehicles:\n')
for v in data:
    print(f"  - {v['name']}: {v['system_count']} systems, {v['total_parts']} parts")

print(f"\n📊 Total Statistics:")
print(f"   Vehicles: {len(data)}")
print(f"   Systems: {sum(v['system_count'] for v in data)}")
print(f"   Parts: {sum(v['total_parts'] for v in data)}")
