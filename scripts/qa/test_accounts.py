import requests


def main() -> None:
    url = "http://localhost:8000/api/accounts"
    payload = {
        "workspace_id": 1,
        "ig_username": "testuser",
        "ig_password": "testpassword",
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        print("Status Code:", response.status_code)
        print("Response Body:", response.text)
    except Exception as exc:
        print("Network Error:", exc)


if __name__ == "__main__":
    main()
