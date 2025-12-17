from flask import Flask, render_template, request, jsonify, send_file
import parselmouth
from parselmouth.praat import call
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from werkzeug.utils import secure_filename
from time import time as get_timestamp


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['OUTPUT_FOLDER'] = 'outputs/'
app.config['PLOT_FOLDER'] = 'static/plots/'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024


os.makedirs('uploads', exist_ok=True)
os.makedirs('outputs', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('static/plots', exist_ok=True)


# Gender 파일 매핑 (새로 추가!)
GENDER_FILES = {
    -5: 'static/voices/voice_male5.wav',
    -4: 'static/voices/voice_male4.wav',
    -3: 'static/voices/voice_male3.wav',
    -2: 'static/voices/voice_male2.wav',
    -1: 'static/voices/voice_male1.wav',
    0: 'static/voices/voice_neutral.wav',
    1: 'static/voices/voice_female1.wav',
    2: 'static/voices/voice_female2.wav',
    3: 'static/voices/voice_female3.wav',
    4: 'static/voices/voice_female4.wav',
    5: 'static/voices/voice_female5.wav'
}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    return jsonify({'filename': filename})


@app.route('/adjust', methods=['POST'])
def adjust_audio():
    data = request.json
    filename = data.get('filename')
    pitch_shift_hz = float(data.get('pitch', 0))
    speed_factor = float(data.get('speed', 1.0))
    gender_level = int(data.get('gender', 0))  # 새로 추가! -5 ~ 5
    
    # Gender preset 선택 (새로 추가!)
    if gender_level in GENDER_FILES:
        input_path = GENDER_FILES[gender_level]
        print(f"\n=== Gender Preset 사용 ===")
        print(f"Gender Level: {gender_level}")
        print(f"파일: {input_path}")
    else:
        # 기존 업로드 파일 사용
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    sound = parselmouth.Sound(input_path)
    
    # 원본 피치 측정
    original_pitch = sound.to_pitch_ac(0.01, 75, 3, False, 0.03, 0.45, 0.01, 0.35, 0.14, 600)
    original_mean = call(original_pitch, "Get mean", 0, 0, "Hertz")
    
    print(f"\n=== 피치 조정 디버깅 ===")
    print(f"원본 평균 피치: {original_mean:.2f} Hz")
    print(f"요청 조정값: {pitch_shift_hz} Hz")
    print(f"목표 피치: {original_mean + pitch_shift_hz:.2f} Hz")
    
    # Manipulation 생성
    manipulation = call(sound, "To Manipulation", 0.01, 75, 600)
    
    # 피치 조정
    if pitch_shift_hz != 0:
        pitch_tier = call(manipulation, "Extract pitch tier")
        num_points = call(pitch_tier, "Get number of points")
        print(f"피치 포인트 개수: {num_points}")
        
        for i in range(1, num_points + 1):
            time_point = call(pitch_tier, "Get time from index", i)
            original_f0 = call(pitch_tier, "Get value at index", i)
            new_f0 = original_f0 + pitch_shift_hz
            new_f0 = max(75, min(600, new_f0))
            
            call(pitch_tier, "Remove point", i)
            call(pitch_tier, "Add point", time_point, new_f0)
            
            if i <= 3:
                print(f"  포인트 {i}: {original_f0:.2f} → {new_f0:.2f} Hz (차이: {new_f0-original_f0:.2f})")
        
        call([pitch_tier, manipulation], "Replace pitch tier")
    
    # 속도 조정
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
    
    actual_change = result_mean - original_mean
    
    print(f"결과 평균 피치: {result_mean:.2f} Hz")
    print(f"실제 변화량: {actual_change:.2f} Hz")
    print(f"오차: {abs(actual_change - pitch_shift_hz):.2f} Hz")
    print("=" * 30 + "\n")
    
    # 저장
    timestamp = int(get_timestamp() * 1000)
    base_name = os.path.splitext(filename)[0] if filename else "preset"
    output_filename = f"adjusted_{base_name}_g{gender_level}_{timestamp}.wav"
    plot_filename = f"plot_{base_name}_g{gender_level}_{timestamp}.png"
    
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    sound.save(output_path, 'WAV')
    
    plot_path = create_praat_plot(sound, plot_filename)
    
    return jsonify({
        'output': output_filename,
        'plot': plot_filename,
        'debug': {
            'gender_level': gender_level,
            'original_pitch': round(original_mean, 2),
            'target_pitch': round(original_mean + pitch_shift_hz, 2),
            'result_pitch': round(result_mean, 2),
            'requested_change': pitch_shift_hz,
            'actual_change': round(actual_change, 2),
            'error': round(abs(actual_change - pitch_shift_hz), 2)
        }
    })


def create_praat_plot(sound, plot_filename):
    """Praat 스타일 파형 + 피치 그래프"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    times = sound.xs()
    values = sound.values[0]
    
    ax1.plot(times, values, linewidth=0.5, color='#2E86AB')
    ax1.set_ylabel('Amplitude', fontsize=12)
    ax1.set_title('Waveform', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim([times[0], times[-1]])
    ax1.set_ylim([-1, 1])
    
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


@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    return send_file(filepath, as_attachment=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
