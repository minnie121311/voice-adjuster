from flask import Flask, render_template, request, jsonify, send_file
import parselmouth
from parselmouth.praat import call
import numpy as np
import os
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from time import time as get_timestamp

app = Flask(__name__)
app.config['STATIC_FOLDER'] = 'static'
app.config['OUTPUT_FOLDER'] = 'static/output'
app.config['PLOT_FOLDER'] = 'static/plots'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs('static', exist_ok=True)
os.makedirs('static/output', exist_ok=True)
os.makedirs('static/plots', exist_ok=True)

# 3가지 메시지 타입 × 11개 gender 파일
def get_audio_file(message_type, gender_level):
    """메시지 타입과 gender 레벨에 따른 파일명 반환"""
    filename = f"{message_type}_gender_{gender_level}.wav"
    filepath = os.path.join(app.config['STATIC_FOLDER'], filename)
    return filepath

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/adjust', methods=['POST'])
def adjust_audio():
    data = request.json
    
    # 파라미터 가져오기
    message_type = data.get('message_type', 'negative')  # negative, positive, informational
    gender_level = int(data.get('gender', 0))  # -5 ~ 5
    pitch_shift_hz = float(data.get('pitch', 0))
    speed_factor = float(data.get('speed', 1.0))
    
    # 파일 경로 설정
    input_path = get_audio_file(message_type, gender_level)
    
    if not os.path.exists(input_path):
        return jsonify({'error': f'File not found: {message_type}_gender_{gender_level}.wav'}), 404
    
    print(f"\n=== Audio Processing ===")
    print(f"Message Type: {message_type}")
    print(f"Gender Level: {gender_level}")
    print(f"File: {input_path}")
    
    try:
        # Praat으로 음성 파일 로드
        sound = parselmouth.Sound(input_path)
        
        # 원본 피치 측정
        original_pitch = sound.to_pitch_ac(0.01, 75, 3, False, 0.03, 0.45, 0.01, 0.35, 0.14, 600)
        original_mean = call(original_pitch, "Get mean", 0, 0, "Hertz")
        
        print(f"Original Pitch: {original_mean:.2f} Hz")
        print(f"Pitch Shift: {pitch_shift_hz} Hz")
        print(f"Speed Factor: {speed_factor}x")
        
        # Manipulation 생성
        manipulation = call(sound, "To Manipulation", 0.01, 75, 600)
        
        # Pitch shift 적용
        if pitch_shift_hz != 0:
            pitch_tier = call(manipulation, "Extract pitch tier")
            num_points = call(pitch_tier, "Get number of points")
            
            for i in range(1, num_points + 1):
                time_point = call(pitch_tier, "Get time from index", i)
                original_f0 = call(pitch_tier, "Get value at index", i)
                new_f0 = original_f0 + pitch_shift_hz
                new_f0 = max(75, min(600, new_f0))
                
                call(pitch_tier, "Remove point", i)
                call(pitch_tier, "Add point", time_point, new_f0)
            
            call([pitch_tier, manipulation], "Replace pitch tier")
        
        # Speed 조정
        if speed_factor != 1.0:
            duration_tier = call(manipulation, "Extract duration tier")
            call(duration_tier, "Add point", 
                 (sound.xmin + sound.xmax) / 2,
                 1.0 / speed_factor)
            call([duration_tier, manipulation], "Replace duration tier")
        
        # 재합성
        sound = call(manipulation, "Get resynthesis (overlap-add)")
        
        # 결과 피치 측정
        result_pitch = sound.to_pitch_ac(0.01, 75, 3, False, 0.03, 0.45, 0.01, 0.35, 0.14, 600)
        result_mean = call(result_pitch, "Get mean", 0, 0, "Hertz")
        
        print(f"Result Pitch: {result_mean:.2f} Hz")
        print("=" * 30 + "\n")
        
        # 저장
        timestamp = int(get_timestamp() * 1000)
        output_filename = f"adjusted_{message_type}_g{gender_level}_{timestamp}.wav"
        plot_filename = f"plot_{message_type}_g{gender_level}_{timestamp}.png"
        
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        sound.save(output_path, 'WAV')
        
        # 플롯 생성
        plot_path = create_praat_plot(sound, plot_filename, message_type, gender_level, pitch_shift_hz, speed_factor)
        
        return jsonify({
            'output': output_filename,
            'plot': plot_filename,
            'debug': {
                'message_type': message_type,
                'gender_level': gender_level,
                'original_pitch': round(original_mean, 2),
                'result_pitch': round(result_mean, 2),
                'pitch_shift': pitch_shift_hz,
                'speed_factor': speed_factor
            }
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def create_praat_plot(sound, plot_filename, message_type, gender_level, pitch_shift, speed_factor):
    """Praat 스타일 파형 + 피치 그래프"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    times = sound.xs()
    values = sound.values[0]
    
    # Waveform
    ax1.plot(times, values, linewidth=0.5, color='#2E86AB')
    ax1.set_ylabel('Amplitude', fontsize=12)
    ax1.set_title(f'{message_type.capitalize()} Message (Gender: {gender_level}, Pitch: {pitch_shift}Hz, Speed: {speed_factor}x)', 
                  fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim([times[0], times[-1]])
    ax1.set_ylim([-1, 1])
    
    # Pitch
    pitch = sound.to_pitch_ac(
        time_step=0.01,
        pitch_floor=75.0,
        max_number_of_candidates=3,
        very_accurate=False,
        silence_threshold=0.03,
        voicing_threshold=0.45,
        octave_cost=0.01,
        octave_jump_cost=0.35,
        voiced_unvoiced_cost=0.14,
        pitch_ceiling=600.0
    )
    
    pitch_values = pitch.selected_array['frequency']
    pitch_times = pitch.xs()
    pitch_values[pitch_values == 0] = np.nan
    
    ax2.plot(pitch_times, pitch_values, linewidth=2, color='#A23B72', marker='o', markersize=1.5)
    ax2.set_xlabel('Time (s)', fontsize=12)
    ax2.set_ylabel('Frequency (Hz)', fontsize=12)
    ax2.set_title('Pitch Contour', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim([times[0], times[-1]])
    
    valid_pitches = pitch_values[~np.isnan(pitch_values)]
    if len(valid_pitches) > 0:
        min_pitch = max(50, np.min(valid_pitches) - 50)
        max_pitch = min(600, np.max(valid_pitches) + 50)
        ax2.set_ylim([min_pitch, max_pitch])
    else:
        ax2.set_ylim([50, 500])
    
    plt.tight_layout()
    
    plot_path = os.path.join(app.config['PLOT_FOLDER'], plot_filename)
    plt.savefig(plot_path, dpi=100, bbox_inches='tight')
    plt.close()
    
    return plot_path

@app.route('/play/<filename>')
def play_file(filename):
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    return send_file(filepath, mimetype='audio/wav')

@app.route('/save', methods=['POST'])
def save_data():
    """CSV 파일로 데이터 저장"""
    data = request.json
    
    csv_filename = 'voice_adjustment_data.csv'
    csv_path = os.path.join(app.config['STATIC_FOLDER'], csv_filename)
    
    file_exists = os.path.exists(csv_path)
    
    try:
        with open(csv_path, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['trial_number', 'message_type', 'gender', 'pitch', 'speed', 'timestamp']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 파일이 없으면 헤더 작성
            if not file_exists:
                writer.writeheader()
            
            # 데이터 추가
            writer.writerow({
                'trial_number': data.get('trial_number'),
                'message_type': data.get('message_type'),
                'gender': data.get('gender'),
                'pitch': data.get('pitch'),
                'speed': data.get('speed'),
                'timestamp': data.get('timestamp')
            })
        
        print(f"Data saved: Trial {data.get('trial_number')}, Type: {data.get('message_type')}")
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Error saving data: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
