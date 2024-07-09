from dotenv import load_dotenv
from imap_tools import MailBox, AND

import os

load_dotenv()

email_user = os.getenv('EMAIL_USER')
email_password = os.getenv('EMAIL_PASS')

print("hello")
def check_latest_email():
    # Connect to Gmail's IMAP server
    with MailBox('imap.gmail.com').login(email_user, email_password, initial_folder='INBOX') as mailbox:
        # Get the latest email
        emails = list(mailbox.fetch(AND(seen=False), limit=1, reverse=True))
        # Print the latest email
        if(len(emails) > 0):
            return emails[0]

# print the email returned by the function
email = check_latest_email()
print(email)
print(email.text)