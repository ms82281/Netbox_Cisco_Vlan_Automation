from flask import Flask, request, jsonify
from redis import Redis
import json
import os
from dotenv import load_dotenv
import hmac
import hashlib
import logging

load_dotenv()

app = Flask(__name__)

redis_client = Redis(
    host=os.getenv('REDIS_HOST'),
    port=int(os.getenv('REDIS_PORT')),
    db=int(os.getenv('REDIS_DB'))
)

def verify_webhook(request_data, signature):
    secret = os.getenv('NETBOX_SECRET')
    computed = hmac.new(
        key=secret.encode(),
        msg=request_data,
        digestmod=hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed, signature)

@app.route('/webhook/vlan', methods=['POST'])
def vlan_webhook():
    signature = request.headers.get('X-Hook-Signature')
    if not signature or not verify_webhook(request.get_data(), signature):
        return jsonify({'error': 'Invalid signature'}), 403

    data = request.json
    if data['model'] != 'vlan':
        return jsonify({'error': 'Invalid model type'}), 400

    # Check if VLAN is protected
    if 'Protected' in data['data']['tags']:
        return jsonify({'error': 'Protected VLAN cannot be modified'}), 403

    # Queue the task
    redis_client.rpush('vlan_tasks', json.dumps(data))
    return jsonify({'status': 'Task queued'}), 202

if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_HOST'),
        port=int(os.getenv('FLASK_PORT'))
    )
