# Inventory Management System

This Streamlit application lets you track and manage inventory across multiple areas of your business. It requires Python 3.11 or newer.

## Getting Started

1. **Create a virtual environment**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Database Configuration

The app expects a PostgreSQL connection string stored in `.streamlit/secrets.toml`:

```toml
[neon]
dsn = "postgresql://user:password@host/dbname"
```

Create the file if it does not exist and replace the connection details with your database credentials.

## Running the App

Activate the virtual environment (if not already active) and launch the application:

```bash
streamlit run app.py
```

## Features Overview

- Google sign-in with PIN protection
- Manage inventory items and receive stock
- Create and track purchase orders
- Selling area and cashier workflow
- Finance utilities and reporting
- Handle returns and issues
- Visual shelf map and near-expiry reports
- Admin user management

