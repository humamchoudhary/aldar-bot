import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
# import ssl
# Replace with your custom SMTP server settings

from flask_mail import Mail, Message


def send_email(to_email, subject, message, mail, html_message=None):
    if not all([to_email, subject, message]):
        return 'Provide all values'

    try:
        msg = Message(
            subject=subject,
            recipients=[to_email],
            body=message,
            html=html_message  # HTML version of the email
        )
        print(msg)
        mail.send(msg)
        # print("Email sent successfully.")
        return 'SEND'
    except Exception as e:
        # print(f"Failed to send email: {e}")
        return f'ERROR: {e}'


if __name__ == "__main__":
    print(send_email('humamchoudhary@gmail.com', 'test', 'test'))
