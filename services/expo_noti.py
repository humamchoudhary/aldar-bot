import requests


def send_push_noti(tokens, title, body, room_id):

    messages = [
        {
            "to": token,
            "sound": "default",  # iOS/Android notification sound
            "title": f"{title}",
            "body": f"{body}",
            "data": {"room_id": f"{room_id}"}  # optional
        }
        for token in tokens
    ]
    print(messages)
    response = requests.post(
        "https://exp.host/--/api/v2/push/send",
        headers={"Content-Type": "application/json"},
        json=messages
    )

    return response
