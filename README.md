
## Prerequisites
Before setting up the project, ensure you have the following installed:
- Python (>= 3.8)
- virtualenv (recommended)
- Gunicorn (for production deployment)

---

## Setup Guide
### Clone the Repository
```bash
git clone https://github.com/humamchoudhary/go-globe-bot
cd go-globe-bot
```

### Create a Virtual Environment (Optional but Recommended)
```bash
python -m venv venv
source venv/bin/activate  # On macOS/Linux
venv\Scripts\activate    # On Windows
```

### Create a Environment Vars
Fill .env file with enviroment variables and keys

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Flask App (Development Mode)
```bash
python app.py
```
The application will start at: `http://127.0.0.1:5000`

---

## Deploy with Gunicorn

### Run the App with Gunicorn
```bash
gunicorn -k eventlet  -w 1 -b 0.0.0.0:8000 app:app
```
- `-b 0.0.0.0:8000` → Binds to port 8000 (change if required)

### Run as a Background Service (Optional)
```bash
nohup gunicorn -k eventlet -w 1 -b 0.0.0.0:8000 app:app &
```

---

## Troubleshooting
- If you get a `ModuleNotFoundError`, ensure you are in the correct virtual environment.
- Make sure no other process is running on port `8000`.

---

## Next Steps
- Use **nginx** as a reverse proxy for production deployment.
- Configure **systemd** for automatic restarts.
- Set up **SSL** for secure communication.

---


