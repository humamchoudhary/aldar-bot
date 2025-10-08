# # import multiprocessing
#
# bind = "0.0.0.0:5000"
#
# # Use eventlet or gevent for WebSockets
# worker_class = "eventlet"  # OR "gevent"
#
# workers = 1  # Recommended worker count
# accesslog = "logs/access.log"
# errorlog = "logs/error.log"
# loglevel = "info"
#
# import multiprocessing
import os

# port = os.environ.get('SVR_PORT')
# bind = f"0.0.0.0:{port}"
# # print(f"Server running at: {bind}")

# Use eventlet or gevent for WebSockets
worker_class = "eventlet"  # OR "gevent"

workers = 1  # Recommended worker count

logfile = "logs/gunicorn.log"
accesslog = logfile
errorlog = logfile
loglevel = "info"


# REMOVE IN PROD

# certfile = './server-cert.pem'  # Path to your SSL certificate
# keyfile = './server-key.pem'
