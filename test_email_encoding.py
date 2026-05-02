from email.message import Message
from email.header import Header

# In standard python `email` library, simply doing msg['Subject'] = value
# does not automatically RFC-2047 encode utf-8 unless it's a Header object in some older versions,
# OR if using the EmailMessage modern API.
msg = Message()
msg['Subject'] = "Re: Hello ⚠️"
print(msg.as_string())

msg2 = Message()
msg2['Subject'] = Header("Re: Hello ⚠️", 'utf-8')
print(msg2.as_string())
