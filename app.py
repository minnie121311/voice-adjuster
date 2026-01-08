from flask import Flask, render_template, request, jsonify, send_file
import os
import csv
from datetime import datetime

app = Flask(__name__)

CSV_FILE = 'experiment_data.csv'

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'trial_number', 'message_type', 'gender', 'pitch', 'speed'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/adjust', methods=['POST'])
def adjust_audio():
    data = request.json
    message_type = data.get('message_type', 'negative')
    gender = int(data.get('gender', 0))
    pitch = int(data.get('pitch', 0))
    speed = float(data.get('speed', 1.0))
    
    # 파일명 생성
    audio_filename = f"{message_type}_gender_{gender}.wav"
    
    return jsonify({
        'output': audio_filename,
        'plot': 'placeholder.png',
        'parameters': {
            'message_type': message_type,
            'gender': gender,
            'pitch': pitch,
            'speed': speed
        }
    })

@app.route('/play/<filename>')
def play_audio(filename):
    return send_file(f'static/{filename}', mimetype='audio/wav')

@app.route('/save', methods=['POST'])
def save_data():
    data = request.json
    
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data.get('timestamp'),
            data.get('trial_number'),
            data.get('message_type'),
            data.get('gender'),
            data.get('pitch'),
            data.get('speed')
        ])
    
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
