#!/usr/bin/env python3
"""
SimpleLogin Postfix Policy Service

A lightweight service that checks incoming emails at SMTP time.
Based on SimpleLogin's email_handler.py.

Created: 2025-06-23
Author: gtstud
"""

import sys
import time
import traceback
import socket
import os
import grp
import logging
import re2 as re
from sqlalchemy.exc import SQLAlchemyError

# Import only what we need from SimpleLogin
from app.db import Session
from app.models import (Alias, User, BlockBehaviourEnum)
from app.alias_utils import try_auto_create
from app.email_utils import is_reverse_alias
from app.log import LOG

# Socket configuration
SOCKET_NAME = 'simplelogin_policy'
SOCKET_PATH = f'/var/spool/postfix/sockets/{SOCKET_NAME}'

# Database retry configuration
MAX_DB_RETRIES = 3
RETRY_DELAY = 1  # seconds


def handle_client(client_socket):
    """Process client connection with pipelining support."""
    buffer = b''

    while True:
        try:
            chunk = client_socket.recv(4096)
            if not chunk:
                LOG.d("Client closed connection")
                return

            buffer += chunk

            while b'\n\n' in buffer:
                request, buffer = buffer.split(b'\n\n', 1)
                process_request(client_socket, request)

        except socket.error as e:
            LOG.e(f"Socket error: {str(e)}")
            return


def process_request(client_socket, request_data):
    """Process a single policy request."""

    # Parse the request
    attributes = {}
    for line in request_data.decode('utf-8').split('\n'):
        line = line.strip()
        if not line:
            continue

        if '=' in line:
            key, value = line.split('=', 1)
            attributes[key] = value

    sender = attributes.get('sender', '')
    recipient = attributes.get('recipient', '')
    client_address = attributes.get('client_address', '')

    LOG.d(f"Policy check: from={sender} to={recipient} client={client_address}")
    start = time.time()

    # Check if this is a valid email address
    if not recipient or '@' not in recipient:
        elapsed = time.time() - start
        LOG.w(f"Policy REJECT: invalid recipient format from={sender} to={recipient} time={elapsed:.3f}s")
        client_socket.sendall(b"action=REJECT Invalid email format\n\n")
        return

    # Process with retry logic for database operations
    for attempt in range(MAX_DB_RETRIES):
        try:
            # Step 1: detect if the recipient is a reverse alias
            if is_reverse_alias(recipient):
                elapsed = time.time() - start
                LOG.i(f"Policy ACCEPT: recipient is reverse alias from={sender} to={recipient} time={elapsed:.3f}s")
                client_socket.sendall(b"action=DUNNO\n\n")
                return

            # Step 2: Try to find the alias using Alias.get_by method
            alias = Alias.get_by(email=recipient)

            if alias:
                regex_mismatch = False
                if alias.sender_regex:
                    try:
                        if not re.search(alias.sender_regex, sender, re.IGNORECASE):
                            regex_mismatch = True
                            LOG.d(f"Sender {sender} does not match alias {alias.email} regex {alias.sender_regex}, treating as disabled")
                    except re.error as e:
                        LOG.w(f"Invalid regex {alias.sender_regex} for alias {alias.email}: {e}")

                # Check if alias is enabled and user is active
                if not alias.enabled or regex_mismatch:
                    # Get the user associated with this alias
                    user = User.get(alias.user_id)
                    elapsed = time.time() - start

                    # Check if user has block_behaviour set to return_2xx
                    if user.block_behaviour == BlockBehaviourEnum.return_2xx:
                        LOG.w(f"Policy PASS (disabled but block_behaviour=return_2xx): from={sender} to={recipient} time={elapsed:.3f}s")
                        client_socket.sendall(b"action=DUNNO\n\n")
                    else:  # user.block_behaviour == BlockBehaviourEnum.return_5xx
                        LOG.w(f"Policy REJECT: disabled alias from={sender} to={recipient} time={elapsed:.3f}s")
                        client_socket.sendall(b"action=REJECT Recipient address disabled\n\n")
                    return

                if not alias.user or not alias.user.is_active:
                    elapsed = time.time() - start
                    LOG.w(f"Policy REJECT: inactive user from={sender} to={recipient} time={elapsed:.3f}s")
                    client_socket.sendall(b"action=REJECT Recipient account inactive\n\n")
                    return

                # Alias exists and is valid
                elapsed = time.time() - start
                LOG.i(f"Policy ACCEPT: existing alias from={sender} to={recipient} time={elapsed:.3f}s")
                client_socket.sendall(b"action=DUNNO\n\n")
                return

            # Step 3: If alias doesn't exist, try to auto-create it
            # try_auto_create handles both SimpleLogin domains and custom domains internally
            try:
                new_alias = try_auto_create(recipient)

                if new_alias:
                    elapsed = time.time() - start
                    LOG.i(f"Policy ACCEPT: auto-created alias from={sender} to={recipient} time={elapsed:.3f}s")
                    client_socket.sendall(b"action=DUNNO\n\n")
                    return
            except Exception as e:
                LOG.e(f"Error in auto-create: {str(e)}")
                Session.rollback()
                client_socket.sendall(b"action=451 4.3.0 Temporary internal error\n\n")
                return

            # If we reach here, we couldn't find or create a valid alias
            elapsed = time.time() - start
            LOG.w(f"Policy REJECT: no valid alias from={sender} to={recipient} time={elapsed:.3f}s")
            client_socket.sendall(b"action=REJECT No such recipient\n\n")
            return

        except SQLAlchemyError as e:
            # Database connection error - try to reconnect
            LOG.w(f"Database error (attempt {attempt + 1}/{MAX_DB_RETRIES}): {str(e)}")

            try:
                Session.remove()
            except:
                pass

            if attempt < MAX_DB_RETRIES - 1:
                # Wait before retry
                LOG.i(f"Waiting {RETRY_DELAY} second(s) before retry")
                time.sleep(RETRY_DELAY)
            else:
                LOG.w(f"All database retries failed, returning temporary failure")
        except Exception as e:
            LOG.e(f"Unexpected error: {str(e)}")
            LOG.e(traceback.format_exc())
            # On any unexpected error, return a temporary failure
            client_socket.sendall(b"action=451 4.3.0 Temporary internal error\n\n")
            return

    # If we get here, all database retries have failed
    elapsed = time.time() - start
    LOG.w(
        f"Policy TEMPFAIL: all database retries failed, deferring email from={sender} to={recipient} time={elapsed:.3f}s")
    client_socket.sendall(b"action=451 4.3.0 Temporary internal error\n\n")


def setup_socket():
    """Create and configure the UNIX socket."""
    # Create socket
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)

    # Set socket permissions to be group readable/writable
    # Make sure simplelogin user is in postfix group
    os.chmod(SOCKET_PATH, 0o770)

    try:
        postfix_uid = os.stat(SOCKET_PATH).st_uid
        postfix_gid = grp.getgrnam('postfix').gr_gid
        os.chown(SOCKET_PATH, postfix_uid, postfix_gid)
    except (KeyError, PermissionError) as e:
        LOG.w(f"Could not set socket ownership: {str(e)}")

    return server


def run_server():
    """Run the policy service server."""
    server = setup_socket()

    # Start listening for connections
    server.listen(100)
    LOG.i(f"SimpleLogin Policy Service started on {SOCKET_PATH}")

    try:
        while True:
            try:
                client, _ = server.accept()
                try:
                    handle_client(client)
                except Exception as e:
                    LOG.e(f"Error handling client: {str(e)}")
                    LOG.e(traceback.format_exc())
                    # On any unhandled exception, return a temporary failure
                    try:
                        client.sendall(b"action=451 4.3.0 Temporary internal error\n\n")
                    except:
                        pass
                finally:
                    try:
                        client.close()
                    except:
                        pass
            except KeyboardInterrupt:
                raise
            except Exception as e:
                LOG.e(f"Error accepting connection: {str(e)}")
                time.sleep(1)
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    try:
        LOG.setLevel(logging.INFO)
        LOG.i("SimpleLogin Policy Service starting up")

        # Initialize database session
        try:
            Session.execute("SELECT 1")
            LOG.i("Database session established")
        except Exception as e:
            LOG.w(f"Initial database connection failed: {str(e)}")
            LOG.w("Will continue and try to connect later")
            try:
                Session.remove()
            except:
                pass

        # Run the server
        run_server()
    except KeyboardInterrupt:
        LOG.i("SimpleLogin Policy Service shutting down")
        sys.exit(0)
    except Exception as e:
        LOG.e(f"Error in policy service: {str(e)}")
        LOG.e(traceback.format_exc())
        sys.exit(1)

