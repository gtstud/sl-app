sed -i 's/regex_mismatch/whitelist_mismatch/g' email_handler.py
sed -i 's/regex_mismatch/whitelist_mismatch/g' tests/test_email_handler.py
sed -i 's/toggle-contact-regex/toggle-contact-whitelist/g' templates/dashboard/alias_contact_manager.html
sed -i 's/regex-label-/whitelist-label-/g' templates/dashboard/alias_contact_manager.html
sed -i 's/Regex mismatch:/Whitelist mismatch:/g' email_handler.py
