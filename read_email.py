from dotenv import load_dotenv
from imap_tools import MailBox, AND

import os
import time
import re

load_dotenv()

email_user = os.getenv('EMAIL_USER')
email_password = os.getenv('EMAIL_PASS')

print("hello")
def fetch_verification_code():
    # give time for verification email to arrive
    time.sleep(10)
    # Connect to Gmail's IMAP server
    with MailBox('imap.gmail.com').login(email_user, email_password, initial_folder='INBOX') as mailbox:
        # Get the latest email
        emails = list(mailbox.fetch(AND(seen=False), limit=1, reverse=True))
        # Print the latest email
        if(len(emails) > 0):
        # find the email whose sender has email address support@accounts.heb.com
            for email in emails:
                if email.from_ == 'support@accounts.heb.com':
                    # return an array of numbers that appear in the text.
                    numbers = re.findall(r'\d+', email.text)
                    # return the first number in the array because it is the verification code
                    return numbers[0]

