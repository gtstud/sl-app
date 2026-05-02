from email.message import Message

def add_or_replace_header(msg: Message, header: str, value: str):
    for i in reversed(range(len(msg._headers))):
        header_name = msg._headers[i][0].lower()
        if header_name == header.lower():
            del msg._headers[i]
    msg[header] = value

msg = Message()
add_or_replace_header(msg, "Subject", "Hello ⚠️")
print(msg.as_string())
