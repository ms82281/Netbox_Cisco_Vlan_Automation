#!/usr/bin/env python3
import sys
import os
import logging
from logging.handlers import RotatingFileHandler

def validate_environment():
    """Validate required environment variables"""
    required_vars = [
        'REDIS_HOST', 'REDIS_PORT', 'REDIS_DB',
        'NETBOX_URL', 'NETBOX_TOKEN',
        'CISCO_USER', 'CISCO_PASS'
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

# Setup logging first
log_dir = os.path.dirname(os.getenv('LOG_FILE', '/app/logs/netauto.log'))
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logger = logging.getLogger('netauto-worker')
logger.setLevel(os.getenv('LOG_LEVEL', 'INFO'))

handler = RotatingFileHandler(
    os.getenv('LOG_FILE', '/app/logs/netauto.log'),
    maxBytes=int(os.getenv('LOG_MAX_SIZE', 10485760)),
    backupCount=int(os.getenv('LOG_BACKUP_COUNT', 5))
)
handler.setFormatter(logging.Formatter(
    os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
))
logger.addHandler(handler)

# Add console handler for better Docker logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(console_handler)

# Validate environment before importing other modules
validate_environment()

from redis import Redis
import json
from dotenv import load_dotenv
import pynetbox
from netmiko import ConnectHandler
import time

load_dotenv()

redis_client = Redis(
    host=os.getenv('REDIS_HOST'),
    port=int(os.getenv('REDIS_PORT')),
    db=int(os.getenv('REDIS_DB'))
)

nb = pynetbox.api(
    url=os.getenv('NETBOX_URL'),
    token=os.getenv('NETBOX_TOKEN')
)
nb.http_session.verify = os.getenv('NETBOX_CERT_VERIFY').lower() == 'true'

def extract_tag_name(tag):
    """Extract tag name from tag object or string"""
    if isinstance(tag, dict):
        return tag.get('name', '')
    return str(tag)

def normalize_vlan_name(name):
    """Normalize VLAN name by replacing spaces with underscores"""
    return name.replace(' ', '_')

def get_target_switches(site_id, vlan_tags):
    logger.debug(f"Processing VLAN with tags: {vlan_tags}")
    
    # Convert tag objects to names
    vlan_tag_names = [extract_tag_name(tag) for tag in vlan_tags]
    logger.debug(f"VLAN tag names: {vlan_tag_names}")
    
    if not vlan_tag_names:
        logger.warning("No tags found in VLAN configuration")
        return []

    logger.debug(f"Getting devices for site_id: {site_id}")
    devices = nb.dcim.devices.filter(site_id=site_id, status='active')
    
    target_switches = []
    for device in devices:
        device_tag_names = [extract_tag_name(tag) for tag in device.tags]
        matching_tags = set(vlan_tag_names) & set(device_tag_names)
        
        if matching_tags:
            logger.debug(f"Device {device.name} matches VLAN tags: {matching_tags}")
            target_switches.append(device)
        else:
            logger.debug(f"Device {device.name} has no matching tags. Device tags: {device_tag_names}")
    
    logger.info(f"Found {len(target_switches)} switches matching VLAN tags: {vlan_tag_names}")
    return target_switches

def configure_vlan(device, vlan_id, vlan_name):
    logger.info(f"Configuring VLAN {vlan_id} ({vlan_name}) on device {device.name}")
    device_tags = [str(tag) for tag in device.tags]
    logger.debug(f"Device {device.name} has tags: {device_tags}")
    
    normalized_name = normalize_vlan_name(vlan_name)
    if normalized_name != vlan_name:
        logger.debug(f"Normalized VLAN name from '{vlan_name}' to '{normalized_name}'")
    
    device_params = {
        'device_type': 'cisco_ios',
        'host': device.primary_ip4.address.split('/')[0],
        'username': os.getenv('CISCO_USER'),
        'password': os.getenv('CISCO_PASS'),
        'port': int(os.getenv('CISCO_SSH_PORT')),
    }
    
    commands = [
        'conf t',
        f'vlan {vlan_id}',
        f'name {normalized_name}',
        'end'
    ]

    try:
        with ConnectHandler(**device_params) as conn:
            conn.send_config_set(commands)
        logger.info(f"Successfully configured VLAN {vlan_id} on {device.name}")
    except Exception as e:
        logger.error(f"Failed to configure VLAN {vlan_id} on {device.name}: {str(e)}")
        raise

def remove_vlan(device, vlan_id):
    logger.info(f"Removing VLAN {vlan_id} from device {device.name}")
    
    device_params = {
        'device_type': 'cisco_ios',
        'host': device.primary_ip4.address.split('/')[0],
        'username': os.getenv('CISCO_USER'),
        'password': os.getenv('CISCO_PASS'),
        'port': int(os.getenv('CISCO_SSH_PORT')),
    }
    
    commands = [
        'conf t',
        f'no vlan {vlan_id}',
        'end'
    ]

    try:
        with ConnectHandler(**device_params) as conn:
            conn.send_config_set(commands)
        logger.info(f"Successfully removed VLAN {vlan_id} from {device.name}")
    except Exception as e:
        logger.error(f"Failed to remove VLAN {vlan_id} from {device.name}: {str(e)}")
        raise

def is_protected_vlan(vlan_tags):
    """Check if VLAN has Protected tag"""
    return any(extract_tag_name(tag) == 'Protected' for tag in vlan_tags)

def process_task():
    logger.info("Starting VLAN task processor")
    task_delay = int(os.getenv('TASK_DELAY', 15))
    logger.info(f"Task processing delay set to {task_delay} seconds")
    
    while True:
        task = redis_client.blpop('vlan_tasks', timeout=1)
        if not task:
            continue

        try:
            logger.info(f"Waiting {task_delay} seconds before processing task...")
            time.sleep(task_delay)
            
            data = json.loads(task[1])
            logger.debug(f"Received data: {data}")
            
            # Validate data structure
            if not isinstance(data, dict):
                raise ValueError("Invalid data format")
                
            vlan_data = data.get('data', {})
            if not vlan_data:
                raise ValueError("Missing VLAN data")
                
            # Extract required fields with validation
            site = vlan_data.get('site')
            if not site or not isinstance(site, dict):
                raise ValueError("Missing or invalid site information")
                
            site_id = site.get('id')
            if not site_id:
                raise ValueError("Missing site ID")
                
            vlan_tags = vlan_data.get('tags', [])
            vlan_id = vlan_data.get('vid')
            vlan_name = vlan_data.get('name')
            event_type = data.get('event', 'unknown')
            
            if not vlan_id or not vlan_name:
                raise ValueError(f"Missing required VLAN information. ID: {vlan_id}, Name: {vlan_name}")
            
            logger.info(f"Processing VLAN {vlan_id} ({vlan_name}) event: {event_type}")
            
            # Handle previous tags based on event type
            previous_tags = []
            if event_type != 'created':  # Only look for previous tags if not a new VLAN
                snapshots = data.get('snapshots', {})
                if snapshots:
                    prechange = snapshots.get('prechange', {})
                    if prechange:
                        previous_tags = prechange.get('tags', [])
            
            current_tag_names = set(extract_tag_name(tag) for tag in vlan_tags)
            previous_tag_names = set(extract_tag_name(tag) for tag in previous_tags)
            
            logger.debug(f"Current tags: {current_tag_names}")
            logger.debug(f"Previous tags: {previous_tag_names}")
            
            # Handle tag removal only for updates
            if event_type != 'created':
                removed_tags = previous_tag_names - current_tag_names
                if removed_tags:
                    logger.info(f"Tags removed: {removed_tags}")
                    affected_switches = get_target_switches(site_id, [{'name': tag} for tag in removed_tags])
                    for switch in affected_switches:
                        if not (set(extract_tag_name(tag) for tag in switch.tags) & current_tag_names):
                            remove_vlan(switch, vlan_data['vid'])
            
            # Handle tag addition
            if current_tag_names:
                target_switches = get_target_switches(site_id, vlan_tags)
                if not target_switches:
                    logger.warning(f"No matching switches found for VLAN {vlan_id}")
                    continue
                
                logger.info(f"Found {len(target_switches)} switches matching VLAN tags: {current_tag_names}")
                for switch in target_switches:
                    configure_vlan(switch, vlan_id, vlan_name)

        except Exception as e:
            logger.error(f"Error processing task: {str(e)}")
            logger.debug("Error details:", exc_info=True)

if __name__ == '__main__':
    try:
        logger.info("Starting VLAN task processor")
        validate_environment()
        load_dotenv()
        process_task()
    except KeyboardInterrupt:
        logger.info("Shutting down worker")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        sys.exit(1)
