import requests
import json

url = "http://localhost:8000/api/accounts"
payload = {
    "user_id": 1,
    "ig_username": "testuser",
    "ig_password": "testpassword"
}
try:
    response = requests.post(url, json=payload)
    print("Status Code:", response.status_code)
    print("Response Body:", response.text)
except Exception as e:
    print("Network Error:", e)
