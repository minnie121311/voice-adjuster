from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import os
import csv
import json
from datetime import datetime
import random
import parselmouth
from parselmouth.praat import call
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import io
import threading
try:
    import openpyxl
    from openpyxl import Workbook
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    print("Warning: openpyxl not installed. Excel export disabled.")


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')


# 연구자 설정
RESEARCHER_EMAIL = 'ucjvmki@ucl.ac.uk'
SMTP_EMAIL = 'minnie1211@gmail.com'
SMTP_PASSWORD = 'apck becz medp lddg'


# CSV 파일들
ALL_DATA_CSV = 'all_participant_data.csv'
PHASE2_CSV = 'phase2_data.csv'
PHASE2_FOLDERS = ['p1', 'p2', 'p3', 'n1', 'n2', 'n3', 'i1', 'i2', 'i3']
OUTPUT_DIR = 'static/adjusted'
DATA_DIR = 'data/phase1'


# 폴더 생성
for folder in [OUTPUT_DIR, DATA_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)


# 통합 CSV 초기화
if not os.path.exists(ALL_DATA_CSV):
    with open(ALL_DATA_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'session_id', 'timestamp', 'data_type', 
            'consent_given', 'consent_time',
            'lsas_fear', 'lsas_avoidance', 'lsas_total',
            'phase1_audio', 'phase1_trustworthiness', 'phase1_anxiety', 
            'phase1_preference', 'phase1_dominance', 'phase1_warmth', 'phase1_listen_time',
            'phase2_folder', 'phase2_formant', 'phase2_pitch'
        ])

if not os.path.exists(PHASE2_CSV):
    with open(PHASE2_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'session_id', 'folder_name', 'file_index', 'formant_value', 'pitch_semitones'])



# ===== 실험 흐름 라우트 =====

@app.route('/')
def home():
    return redirect(url_for('welcome'))


@app.route('/welcome')
def welcome():
    return render_template('welcome.html')


@app.route('/consent')
def consent():
    return render_template('consent.html')


@app.route('/submit-consent', methods=['POST'])
def submit_consent():
    try:
        session['consent_given'] = True
        session['consent_time'] = datetime.now().isoformat()

        if 'study_session_id' not in session:
            session['study_session_id'] = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

        with open(ALL_DATA_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                session['study_session_id'],
                datetime.now().isoformat(),
                'consent',
                True,
                session['consent_time'],
                '', '', '', '', '', '', '', '', '', '', '', '', ''
            ])

        print(f"Consent saved: {session['study_session_id']}")

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/lsas')
def lsas():
    return render_template('lsas.html')


@app.route('/submit-lsas', methods=['POST'])
def submit_lsas():
    try:
        data = request.json
        responses = data.get('responses', [])

        fear_total = sum(r['fear'] for r in responses)
        avoidance_total = sum(r['avoidance'] for r in responses)
        total_score = fear_total + avoidance_total

        session['lsas_fear'] = fear_total
        session['lsas_avoidance'] = avoidance_total
        session['lsas_total'] = total_score

        with open(ALL_DATA_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                session.get('study_session_id'),
                datetime.now().isoformat(),
                'lsas',
                '', '',
                fear_total, avoidance_total, total_score,
                '', '', '', '', '', '', '', '', '', ''
            ])

        print(f"LSAS saved: Fear={fear_total}, Avoidance={avoidance_total}, Total={total_score}")

        return jsonify({'success': True})
    except Exception as e:
        print(f"Error in submit_lsas: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/phase1')
def phase1():
    if 'participant_id' not in session:
        session['participant_id'] = f"P{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return render_template('phase1.html')


@app.route('/api/submit_phase1', methods=['POST'])
def submit_phase1():
    try:
        data = request.json
        participant_id = data.get('participant_id', 'anonymous')
        responses = data.get('responses', [])

        with open(ALL_DATA_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for resp in responses:
                writer.writerow([
                    session.get('study_session_id', participant_id),
                    resp.get('timestamp'),
                    'phase1',
                    '', '',
                    '', '', '',
                    resp.get('filename'),
                    resp.get('trustworthiness'),
                    resp.get('anxiety'),
                    resp.get('preference'),
                    resp.get('dominance'),
                    resp.get('warmth'),
                    resp.get('listenTime', 0),
                    '', '', ''
                ])

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{participant_id}_{timestamp}.json"
        filepath = os.path.join(DATA_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Phase 1 data saved: {filename}")

        threading.Thread(target=send_phase1_email, args=(participant_id, len(responses)), daemon=True).start()

        return jsonify({
            'success': True,
            'message': 'Data saved successfully',
            'participant_id': participant_id
        })

    except Exception as e:
        print(f"Error in submit_phase1: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


def send_phase1_email(participant_id, response_count):
    try:
        print(f"Sending Phase 1 email for: {participant_id}")

        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = RESEARCHER_EMAIL
        msg['Subject'] = f'Voice Study - Phase 1 Complete - {participant_id}'

        body = f'''
A participant has completed Phase 1 (Voice Evaluation).

Participant ID: {participant_id}
Session ID: {session.get('study_session_id', 'N/A')}
Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Responses: {response_count} audio evaluations

Data will be included in final Excel file after Phase 2 completion.
        '''

        msg.attach(MIMEText(body, 'plain'))

        if SMTP_EMAIL and SMTP_PASSWORD:
            sent = False
            for port, use_ssl in [(587, False), (465, True)]:
                try:
                    if use_ssl:
                        server = smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=15)
                    else:
                        server = smtplib.SMTP('smtp.gmail.com', port, timeout=15)
                        server.starttls()
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    server.quit()
                    print(f"✓ Phase 1 email sent to {RESEARCHER_EMAIL} via port {port}")
                    sent = True
                    break
                except Exception as port_err:
                    print(f"Port {port} failed: {port_err}")

    except Exception as e:
        print(f"Phase 1 email error: {str(e)}")


@app.route('/phase2')
def phase2():
    return render_template('phase2.html')


@app.route('/start-phase2', methods=['POST'])
def start_phase2():
    try:
        shuffled = PHASE2_FOLDERS.copy()
        random.shuffle(shuffled)

        session['phase2_folders'] = shuffled
        session['current_index'] = 0

        if 'session_id' not in session:
            session['session_id'] = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

        print(f"Phase 2 started: {session['session_id']}")

        return jsonify({
            'current_folder': shuffled[0],
            'index': 0,
            'total': len(shuffled)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/adjust-voice', methods=['POST'])
def adjust_voice():
    try:
        data = request.json
        folder = data.get('folder')
        formant = int(data.get('formant', 0))
        pitch_semitones = float(data.get('pitch', 0))  # 🔥 int → float

        # 🔥 범위 제한 -5 ~ +5
        pitch_semitones = max(-5, min(5, pitch_semitones))

        formant_file = f'static/audio/{folder}/{folder}_{formant}.wav'

        if not os.path.exists(formant_file):
            return jsonify({'error': f'File not found'}), 404

        # 🔥 0.01 미만은 원본 반환
        if abs(pitch_semitones) < 0.01:
            return jsonify({
                'output_file': f'audio/{folder}/{folder}_{formant}.wav',
                'parameters': {'formant': formant, 'pitch': 0}
            })

        sound = parselmouth.Sound(formant_file)
        pitch_factor = 2.0 ** (pitch_semitones / 12.0)

        try:
            manipulation = call(sound, "To Manipulation", 0.01, 75, 600)
            pitch_tier = call(manipulation, "Extract pitch tier")
            call(pitch_tier, "Multiply frequencies", sound.xmin, sound.xmax, pitch_factor)
            call([pitch_tier, manipulation], "Replace pitch tier")
            sound = call(manipulation, "Get resynthesis (overlap-add)")
        except:
            return jsonify({
                'output_file': f'audio/{folder}/{folder}_{formant}.wav',
                'parameters': {'formant': formant, 'pitch': 0}
            })

        max_val = max(abs(sound.get_value(t)) for t in sound.xs())
        if max_val > 0.95:
            sound = sound * (0.95 / max_val)

        # 🔥 파일명에 소수점 포함
        output_filename = f"{folder}_f{formant}_p{pitch_semitones:.1f}.wav"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        sound.save(output_path, 'WAV')

        return jsonify({
            'output_file': f'adjusted/{output_filename}',
            'parameters': {'formant': formant, 'pitch': pitch_semitones}
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/play/<path:filepath>')
def play_audio(filepath):
    try:
        file_path = f'static/{filepath}'
        if os.path.exists(file_path):
            return send_file(file_path, mimetype='audio/wav')
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/submit-adjustment', methods=['POST'])
def submit_adjustment():
    try:
        data = request.json
        folders = session.get('phase2_folders', [])
        index = session.get('current_index', 0)

        with open(PHASE2_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                session.get('session_id'),
                data.get('folder'),
                index,
                data.get('formant'),
                data.get('pitch')
            ])

        with open(ALL_DATA_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                session.get('study_session_id', session.get('session_id')),
                datetime.now().isoformat(),
                'phase2',
                '', '',
                '', '', '',
                '', '', '', '', '', '', '',
                data.get('folder'),
                data.get('formant'),
                data.get('pitch')
            ])

        session['current_index'] = index + 1

        if session['current_index'] >= len(folders):
            sid = session.get('study_session_id')
            threading.Thread(target=send_complete_excel, args=(sid,), daemon=True).start()

            return jsonify({
                'completed': True,
                'message': 'Study completed! Thank you.'
            })

        return jsonify({
            'success': True,
            'next_folder': folders[session['current_index']],
            'index': session['current_index'],
            'total': len(folders)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def send_complete_excel(session_id):
    try:
        if not session_id:
            print("send_complete_excel: session_id is None, skipping")
            return

        print(f"Creating Excel file for session: {session_id}")

        if not EXCEL_AVAILABLE:
            print("Excel export not available")
            return

        wb = Workbook()
        wb.remove(wb.active)

        # 참여자 데이터 읽기
        participant_data = []
        with open(ALL_DATA_CSV, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                if row[0] == session_id:
                    participant_data.append(row)

        # Summary sheet
        ws_summary = wb.create_sheet("Summary")
        ws_summary.append(['Session ID', session_id])
        ws_summary.append(['Completed', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        ws_summary.append([])

        # Data sheets
        ws_consent = wb.create_sheet("Consent")
        ws_consent.append(['Session ID', 'Timestamp', 'Consent Given', 'Consent Time'])

        ws_lsas = wb.create_sheet("LSAS")
        ws_lsas.append(['Session ID', 'Timestamp', 'Fear Score', 'Avoidance Score', 'Total Score'])

        ws_phase1 = wb.create_sheet("Phase 1")
        ws_phase1.append(['Session ID', 'Timestamp', 'Audio File', 'Trustworthiness', 'Anxiety', 'Preference', 'Dominance', 'Warmth', 'Listen Time'])

        ws_phase2 = wb.create_sheet("Phase 2")
        ws_phase2.append(['Session ID', 'Timestamp', 'Folder', 'Formant', 'Pitch'])

        for row in participant_data:
            data_type = row[2]
            if data_type == 'consent':
                ws_consent.append([row[0], row[1], row[3], row[4]])
            elif data_type == 'lsas':
                ws_lsas.append([row[0], row[1], row[5], row[6], row[7]])
            elif data_type == 'phase1':
                ws_phase1.append([row[0], row[1], row[8], row[9], row[10], row[11], row[12], row[13], row[14]])
            elif data_type == 'phase2':
                ws_phase2.append([row[0], row[1], row[15], row[16], row[17]])

        # Save Excel
        excel_filename = f'study_data_{session_id}.xlsx'
        excel_path = os.path.join(DATA_DIR, excel_filename)
        wb.save(excel_path)

        # Send email
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = RESEARCHER_EMAIL
        msg['Subject'] = f'Voice Study - COMPLETE - {session_id}'

        body = f'''
A participant has completed the entire study!

Session ID: {session_id}
Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Complete data is attached as Excel file with tabs:
- Summary
- Consent
- LSAS
- Phase 1 (36 voice evaluations)
- Phase 2 (9 voice adjustments)
        '''

        msg.attach(MIMEText(body, 'plain'))

        # Attach Excel
        with open(excel_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={excel_filename}')
            msg.attach(part)

        if SMTP_EMAIL and SMTP_PASSWORD:
            sent = False
            last_err = None
            for port, use_ssl in [(587, False), (465, True)]:
                try:
                    if use_ssl:
                        server = smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=15)
                    else:
                        server = smtplib.SMTP('smtp.gmail.com', port, timeout=15)
                        server.starttls()
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    server.quit()
                    print(f"✓ Excel file sent to {RESEARCHER_EMAIL} via port {port}")
                    sent = True
                    break
                except Exception as port_err:
                    last_err = port_err
                    print(f"Port {port} failed: {port_err}")
            if not sent:
                raise last_err

    except Exception as e:
        print(f"Excel email error: {str(e)}")
        import traceback
        traceback.print_exc()



@app.route('/admin/test-email')
def test_email():
    admin_key = request.args.get('key')
    if admin_key != 'ucl-voice-study-2026':
        return jsonify({'error': 'Unauthorized'}), 403

    results = []
    for port, use_ssl in [(587, False), (465, True)]:
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_EMAIL
            msg['To'] = RESEARCHER_EMAIL
            msg['Subject'] = 'Voice Study - Email Test'
            msg.attach(MIMEText(f'Test email from Railway via port {port}', 'plain'))

            if use_ssl:
                server = smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=15)
            else:
                server = smtplib.SMTP('smtp.gmail.com', port, timeout=15)
                server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            results.append({'port': port, 'status': 'success'})
            break
        except Exception as e:
            results.append({'port': port, 'status': 'failed', 'error': str(e)})

    return jsonify({'results': results})


@app.route('/admin/csv-status')
def csv_status():
    admin_key = request.args.get('key')
    if admin_key != 'ucl-voice-study-2026':
        return jsonify({'error': 'Unauthorized'}), 403

    rows = 0
    last_session = None
    if os.path.exists(ALL_DATA_CSV):
        with open(ALL_DATA_CSV, 'r') as f:
            lines = f.readlines()
        rows = len(lines) - 1
        if rows > 0:
            last_session = lines[-1].split(',')[0]

    excel_files = []
    if os.path.exists(DATA_DIR):
        excel_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.xlsx')]

    return jsonify({
        'csv_rows': rows,
        'last_session': last_session,
        'excel_files': excel_files
    })

@app.route('/thankyou')
def thankyou():
    return render_template('thankyou.html')


@app.route('/download-csv')
def download_csv():
    admin_key = request.args.get('key')
    if admin_key != 'ucl-voice-study-2026':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        if os.path.exists(ALL_DATA_CSV):
            return send_file(ALL_DATA_CSV, as_attachment=True, download_name='all_study_data.csv')
        else:
            return jsonify({'error': 'No data available'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask app on port {port}...")
    print(f"Excel export: {'Enabled' if EXCEL_AVAILABLE else 'Disabled (install openpyxl)'}")
    app.run(host='0.0.0.0', port=port, debug=True)
