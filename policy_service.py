#!/usr/bin/env python3
"""
SimpleLogin Postfix Policy Service

This lightweight service determines whether to accept or reject incoming emails
at SMTP time by checking if a valid alias exists or can be auto-created.

This service integrates with SimpleLogin's existing codebase and functions.
"""

import sys
import time
import traceback
import socket
import os
import pwd
import grp
import sqlalchemy.exc

# Import Flask and load the app
from app import create_app
from app.email_utils import get_email_domain_part
from app.extensions import db
from app.log import LOG
from app.models import Alias, CustomDomain
from app.alias_utils import try_auto_create

# Initialize Flask app to load all models and configuration
app = create_app()
app.app_context().push()

# Socket configuration
SOCKET_NAME = 'simplelogin_policy'
SOCKET_PATH = f'/var/spool/postfix/private/{SOCKET_NAME}'

# Maximum number of database retries
MAX_DB_RETRIES = 3


def reconnect_db():
    """Reconnect to the database if the connection was lost."""
    LOG.w("Database connection lost, reconnecting...")
    try:
        db.session.remove()
        db.engine.dispose()
        # Just creating a new session should establish a new connection
        db.session.execute("SELECT 1")
        LOG.i("Database connection reestablished")
        return True
    except Exception as e:
        LOG.e(f"Failed to reconnect to database: {str(e)}")
        return False


def handle_client(client_socket):
    """Process client connection with correct pipelining support."""
    # Buffer to store incoming data
    buffer = b''

    # Continue processing until client disconnects
    while True:
        try:
            # Read some data
            chunk = client_socket.recv(4096)
            if not chunk:  # Connection closed by client
                LOG.d("Client closed connection")
                return

            # Add to our buffer
            buffer += chunk

            # Process as many complete requests as we have in the buffer
            while b'\n\n' in buffer:
                # Extract one complete request
                request, buffer = buffer.split(b'\n\n', 1)

                # Process this request
                process_request(client_socket, request)

        except socket.error as e:
            LOG.e(f"Socket error while reading request: {str(e)}")
            return


def process_request(client_socket, request_data):
    """Process a single complete policy request."""
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

    # Process the email with retry logic for database operations
    for attempt in range(MAX_DB_RETRIES):
        try:
            # Step 1: Try to find the alias
            alias = Alias.get_by(email=recipient)

            if alias:
                # Check if alias is enabled and user is active
                if not alias.enabled:
                    elapsed = time.time() - start
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

            # Step 2: If alias doesn't exist, try to auto-create it
            domain_part = get_email_domain_part(recipient)

            # Get the custom domain if this is a custom domain
            custom_domain = CustomDomain.get_by_domain(domain_part)

            # Try to auto-create an alias using SimpleLogin's function with correct parameters
            new_alias = try_auto_create(recipient)

            if new_alias:
                # Successfully auto-created an alias
                elapsed = time.time() - start
                LOG.i(f"Policy ACCEPT: auto-created alias from={sender} to={recipient} time={elapsed:.3f}s")
                client_socket.sendall(b"action=DUNNO\n\n")
                return

            # Step 3: If we can't find or create an alias, reject the email
            elapsed = time.time() - start
            LOG.w(f"Policy REJECT: no valid alias from={sender} to={recipient} time={elapsed:.3f}s")
            client_socket.sendall(b"action=REJECT No such recipient\n\n")
            return

        except (sqlalchemy.exc.OperationalError, sqlalchemy.exc.StatementError) as e:
            # Database connection issues - try to reconnect
            LOG.w(f"Database error (attempt {attempt + 1}/{MAX_DB_RETRIES}): {str(e)}")

            try:
                db.session.rollback()
            except:
                pass

            if attempt < MAX_DB_RETRIES - 1:
                # Try to reconnect before the next attempt
                if reconnect_db():
                    LOG.i(f"Retrying operation after reconnection")
                    continue
                else:
                    LOG.w(f"Reconnection failed, trying again in 1 second")
                    time.sleep(1)  # Small delay before retry
                    continue

    # If we get here, all retries failed - let the email pass through
    elapsed = time.time() - start
    LOG.i(
        f"Policy PASS: all database retries failed, letting email through from={sender} to={recipient} time={elapsed:.3f}s")
    client_socket.sendall(b"action=DUNNO\n\n")


def setup_socket():
    """Create and configure the UNIX socket for the policy service."""
    # Create socket
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)

    # Set socket permissions
    os.chmod(SOCKET_PATH, 0o660)

    return server


def run_server():
    """Run the policy service server."""
    server = setup_socket()

    # Start listening for connections
    server.listen(100)  # Allow up to 100 queued connections
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
                    # On any unhandled exception, try to tell Postfix to continue processing
                    try:
                        client.sendall(b"action=DUNNO\n\n")
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
                time.sleep(1)  # Prevent CPU spin if there's a persistent issue
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    try:
        LOG.i("SimpleLogin Policy Service starting up")

        # Initial database connection
        for attempt in range(MAX_DB_RETRIES):
            try:
                # Just executing a simple query will establish the connection
                db.session.execute("SELECT 1")
                LOG.i("Database connection established")
                break
            except Exception as e:
                if attempt < MAX_DB_RETRIES - 1:
                    LOG.w(f"Failed to connect to database (attempt {attempt + 1}/{MAX_DB_RETRIES}): {str(e)}")
                    time.sleep(2)  # Wait before retry
                else:
                    LOG.e(f"Failed to connect to database after {MAX_DB_RETRIES} attempts: {str(e)}")
                    LOG.e("Will continue and pass emails through until database is available")

        # Run the server
        run_server()
    except KeyboardInterrupt:
        LOG.i("SimpleLogin Policy Service shutting down")
        sys.exit(0)
    except Exception as e:
        LOG.e(f"Error in policy service: {str(e)}")
        LOG.e(traceback.format_exc())
        sys.exit(1)