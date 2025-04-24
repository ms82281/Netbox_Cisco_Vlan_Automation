# Cisco / Netbox Automation Webhook

A middleware application that automatically synchronizes VLAN configurations between Netbox and Cisco switches based on device tags.

## Features

- Automatic VLAN synchronization based on device tags
- Protected VLAN support to prevent automated changes
- Site-based VLAN segregation
- Redis-based task queue for parallel processing
- Comprehensive logging system
- Docker support for easy deployment
- Automatic VLAN name normalization (spaces to underscores)

## Architecture

- **API**: Flask-based webhook receiver for Netbox
- **Worker**: Background processor for VLAN configurations
- **Redis**: Message queue for task distribution

## Requirements

- Python 3.9+
- Redis
- Docker and Docker Compose (for containerized deployment)
- Netbox 4.2+
- Cisco IOS devices

## Configuration

Create a `.env` file with the following settings:

```env
# Cisco Device Access
CISCO_USER=username
CISCO_PASS=password
CISCO_SSH_PORT=22
CISCO_REST_PORT=443

# Netbox Configuration
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your_token
NETBOX_SECRET=webhook_secret
NETBOX_CERT_VERIFY=false

# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Flask Configuration
FLASK_HOST=0.0.0.0
FLASK_PORT=5005

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=/app/logs/netauto.log
LOG_FORMAT=%(asctime)s - %(name)s - %(levelname)s - %(message)s
LOG_MAX_SIZE=10485760
LOG_BACKUP_COUNT=5
```

## Deployment

### Install Docker and Docker-Compose (debian / Ubuntu)

```apt update
apt upgrade -y
apt install curl -y
apt install docker-compose -y
curl -sSL https://get.docker.com/ | sh
```

### Using Docker Compose

1. Build and start the services:
```bash
docker-compose up -d
```

2. View logs:
```bash
docker-compose logs -f worker
docker-compose logs -f api
```

3. Stop services:
```bash
docker-compose down
```

### Manual Installation

1. Create virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start Redis server
4. Run the API: `python api.py`
5. Run the worker: `python worker.py`

## Netbox Configuration

1. Create a webhook in Netbox:
   - URL: `http://your-server:5005/webhook/vlan`
   - HTTP Method: POST
   - Content Type: application/json
   - Additional Headers: `X-Hook-Secret: your_webhook_secret`
   - SSL Verification: As needed
   - Triggers: VLAN updates

2. Tag your devices and VLANs:
   - Use matching tags between VLANs and devices
   - Add "Protected" tag to VLANs that should not be modified
   - Ensure devices have correct site assignments

## Tag-based VLAN Distribution

VLANs are distributed to devices based on matching tags:
- VLANs tagged with "Core Switch" will be configured on devices with the same tag
- Multiple tags on a VLAN will distribute to all matching devices
- The "Protected" tag prevents automated modifications
- Tags are site-specific - VLANs only configure on devices in the same site
- VLAN names are automatically normalized (spaces replaced with underscores)

## Logging

Logs are stored in `/app/logs/netauto.log` with automatic rotation:
- Maximum file size: 10MB
- Keeps last 5 backup files
- Configurable log level through LOG_LEVEL environment variable

## Security Considerations

- Use strong passwords for device access
- Protect the Netbox webhook secret
- Consider enabling SSL verification in production
- Restrict access to the API endpoint
- Protect Redis with authentication in production

## Troubleshooting

1. Check logs in `/app/logs/netauto.log`
2. Verify Redis connectivity
3. Ensure device credentials are correct
4. Verify Netbox webhook configuration
5. Check device and VLAN tags match exactly

## Recreate Docker images after code updates

After changing the code, the docker images have to be recreated and updated.

```docker-compose down
docker-compose build
docker-compose up -d
```