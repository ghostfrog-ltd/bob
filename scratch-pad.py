import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("SMTP_HOST")
port = int(os.getenv("SMTP_PORT", "587"))
user = os.getenv("SMTP_USERNAME")
password = os.getenv("SMTP_PASSWORD")
from_addr = os.getenv("SMTP_FROM") or user
to_addr = os.getenv("SMTP_TO")

print("Connecting to:", host, port)

msg = EmailMessage()
msg["From"] = from_addr
msg["To"] = to_addr
msg["Subject"] = "Zoho auth test"
msg.set_content("If you see this, SMTP auth is working.")

with smtplib.SMTP(host, port, timeout=30) as s:
    s.starttls()
    s.login(user, password)
    s.send_message(msg)

print("Sent OK")
