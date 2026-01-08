from flask import Flask, render_template, request, jsonify, send_file
import os
import csv
from datetime import datetime

app = Flask(__name__)

# CSV 파일 경로
CSV_FILE = 'experiment_data.csv'

# CSV 헤더 초기화
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'trial_number', 'message_type', 'gender', 'pitch', 'speed'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_audio():
    data = request.json
    message_type = data.get('message_type', 'negative')
    gender = int(data.get('gender', 0))
    pitch = float(data.get('pitch', 1.0))
    speed = float(data.get('speed', 1.0))
    
    # 새로운 파일 경로
    audio_file = f'static/{message_type}_gender_{gender}.wav'
    
    return jsonify({
        'audio_url': f'/{audio_file}',
        'parameters': {
            'message_type': message_type,
            'gender': gender,
            'pitch': pitch,
            'speed': speed
        }
    })

@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.json
    
    # CSV에 데이터 저장
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(),
            data.get('trial_number'),
            data.get('message_type'),
            data.get('gender'),
            data.get('pitch'),
            data.get('speed')
        ])
    
    return jsonify({'status': 'success', 'message': 'Data saved successfully'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
