# SimpleLogin Manual Migration Plan (to Master)

This guide provides a step-by-step procedure to migrate your custom, non-Docker SimpleLogin installation from the `known-working-my-setup` state to the current `master` branch.

## 1. Prerequisites
- **Python Version**: The repository has updated its target to Python 3.12, but since you are running **Python 3.13.5**, you are well within the required spec. No Python runtime updates are needed.
- **Custom Scripts (`policy_service.py`)**: A thorough review of your custom `policy_service.py` confirms that the SimpleLogin functions and models it imports (`try_auto_create`, `is_reverse_alias`, `Alias`, `User`, `BlockBehaviourEnum`, and `LOG`) have not changed in their interface or location. Therefore, **no code changes to your script are required.**

## 2. Migration Steps

### Step 2.1: Stop Running Services
To avoid database corruption or inconsistencies during migration, stop all running SimpleLogin services.

```bash
# Example assuming systemd services. Adjust if you use a different supervisor.
sudo systemctl stop simplelogin-webapp
sudo systemctl stop simplelogin-email-handler
sudo systemctl stop simplelogin-job-runner

# Stop your custom policy service
sudo systemctl stop postfix-policy-service
```

### Step 2.2: Fetch and Checkout `master`
Pull the latest changes from the `master` branch.

```bash
git checkout master
git pull origin master
```

### Step 2.3: Update Dependencies
The upstream `master` branch has transitioned to `uv` and `pyproject.toml` (introducing a `uv.lock` file). You must sync your virtual environment with the new dependencies.

If you have `uv` installed:
```bash
uv sync
```

Or, if you use standard `pip`, you can still install from the pyproject configuration:
```bash
pip install -e .
# Alternatively, if there is a requirements.txt generated:
# pip install -r requirements.txt
```

### Step 2.4: Run Database Migrations
There are several new database migrations (e.g., adding mailbox flags, FIDO credential metadata, etc.). Run Alembic/Flask-Migrate to apply these database schema updates:

```bash
# Ensure your environment variables (like DB_URI, FLASK_SECRET, etc.) are exported
# or read from your .env file
flask db upgrade
```

### Step 2.5: Test `policy_service.py` (Optional but Recommended)
Before starting everything, you can quickly test if your policy service imports and runs successfully in the updated environment.

```bash
# Assuming your virtual environment is activated
python3 policy_service.py
# If it says "SimpleLogin Policy Service starting up" without errors, hit Ctrl+C to stop it.
```

### Step 2.6: Restart Services
Once the database is upgraded and dependencies are installed, start your services back up.

```bash
sudo systemctl start simplelogin-webapp
sudo systemctl start simplelogin-email-handler
sudo systemctl start simplelogin-job-runner

# Start your custom policy service
sudo systemctl start postfix-policy-service
```

### Step 2.7: Verify the App
1. Go to your web application interface and verify you can log in.
2. Send a test email through one of your aliases to confirm the `email_handler.py` and `policy_service.py` are functioning perfectly.

## Summary
The migration primarily involves applying the new dependencies and database schemas. Your custom `policy_service.py` is safely insulated from these upstream changes!
