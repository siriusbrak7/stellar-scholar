from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
import json
import os
from datetime import datetime
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash
import time
import threading

app = Flask(__name__)
app.config.from_object(Config)

# FIXED: Use persistent data directory that survives deployments
def get_data_dir():
    """Get persistent data directory path"""
    # On Render, use /tmp/data for persistence between deployments
    if 'RENDER' in os.environ:
        data_dir = '/tmp/data'
    else:
        # Local development
        data_dir = 'data'
    
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

# Helper functions for JSON file operations
def load_json(filename):
    """Load data from JSON file"""
    filepath = os.path.join(get_data_dir(), filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}

def save_json(filename, data):
    """Save data to JSON file"""
    filepath = os.path.join(get_data_dir(), filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

# Initialize data files if they don't exist with demo data
def initialize_data():
    """Initialize data files with demo content if empty"""
    for filename in ['users.json', 'prompts.json', 'submissions.json']:
        filepath = os.path.join(get_data_dir(), filename)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            save_json(filename, {})
    
    # Add demo teacher account if no users exist
    users = load_json('users.json')
    if not users:
        demo_teacher = {
            'username': 'teacher',
            'password_hash': generate_password_hash('teach123'),
            'role': 'teacher',
            'created_at': datetime.now().isoformat()
        }
        users['teacher'] = demo_teacher
        save_json('users.json', users)
        print("Demo teacher account created: username='teacher', password='teach123'")

# Initialize data on app start
initialize_data()

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        users = load_json('users.json')
        user = users.get(session['user_id'])
        if not user or user['role'] != 'teacher':
            flash('Access denied. Teachers only.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def keep_alive():
    """Simple background thread to prevent spin-down"""
    while True:
        time.sleep(300)  # Ping every 5 minutes
        try:
            # This keeps the service active
            print(f"Keep-alive ping at {datetime.now().isoformat()}")
        except:
            pass

# Start keep-alive thread when app starts
if 'RENDER' in os.environ:
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    print("Keep-alive thread started for Render deployment")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        users = load_json('users.json')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role')
        grade = request.form.get('grade') if role == 'student' else None
        
        # Validation
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('register.html')
        
        if username in users:
            flash('Username already exists. Please choose another.', 'danger')
            return render_template('register.html')
        
        if role == 'student' and not grade:
            flash('Please select your grade level.', 'danger')
            return render_template('register.html')
        
        # Create new user
        user_data = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
            'grade': grade,
            'created_at': datetime.now().isoformat()
        }
        
        users[username] = user_data
        save_json('users.json', users)
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_json('users.json')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user = users.get(username)
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = username
            session['role'] = user['role']
            flash(f'Welcome back, {username}!', 'success')
            
            if user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    prompts = load_json('prompts.json')
    submissions = load_json('submissions.json')
    users = load_json('users.json')
    
    # Count submissions per prompt
    prompt_stats = {}
    for prompt_id in prompts:
        prompt_stats[prompt_id] = {
            'total': 0,
            'graded': 0
        }
        for sub_id, sub in submissions.items():
            if sub['prompt_id'] == prompt_id:
                prompt_stats[prompt_id]['total'] += 1
                if sub.get('grade') is not None:
                    prompt_stats[prompt_id]['graded'] += 1
    
    # Get top 5 students for leaderboard preview
    top_students = []
    student_scores = {}
    
    for sub_id, sub in submissions.items():
        if sub.get('grade') is not None:
            student_id = sub['student_id']
            if student_id not in student_scores:
                student_scores[student_id] = {
                    'grades': [],
                    'username': student_id,
                    'grade_level': users.get(student_id, {}).get('grade', 'N/A')
                }
            student_scores[student_id]['grades'].append(sub['grade'])
    
    for student_id, data in student_scores.items():
        if data['grades']:
            avg_score = sum(data['grades']) / len(data['grades'])
            top_students.append({
                'username': data['username'],
                'grade_level': data['grade_level'],
                'avg_score': round(avg_score, 2)
            })
    
    top_students.sort(key=lambda x: x['avg_score'], reverse=True)
    top_students = top_students[:5]  # Top 5 only
    
    return render_template('teacher_dashboard.html', 
                         prompts=prompts, 
                         prompt_stats=prompt_stats,
                         top_students=top_students)

@app.route('/teacher/create_prompt', methods=['GET', 'POST'])
@teacher_required
def create_prompt():
    if request.method == 'POST':
        prompts = load_json('prompts.json')
        
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        grade_level = request.form.get('grade_level')
        
        if not title or not description or not grade_level:
            flash('All fields are required.', 'danger')
            return render_template('create_prompt.html')
        
        prompt_id = f"prompt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        prompts[prompt_id] = {
            'id': prompt_id,
            'title': title,
            'description': description,
            'grade_level': grade_level,
            'created_by': session['user_id'],
            'created_at': datetime.now().isoformat()
        }
        
        save_json('prompts.json', prompts)
        flash('Prompt created successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))
    
    return render_template('create_prompt.html')

@app.route('/teacher/grade/<prompt_id>', methods=['GET', 'POST'])
@teacher_required
def grade_submissions(prompt_id):
    prompts = load_json('prompts.json')
    submissions = load_json('submissions.json')
    users = load_json('users.json')
    
    prompt = prompts.get(prompt_id)
    if not prompt:
        flash('Prompt not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if request.method == 'POST':
        submission_id = request.form.get('submission_id')
        grade = request.form.get('grade')
        feedback = request.form.get('feedback', '').strip()
        
        if submission_id in submissions:
            try:
                grade_value = float(grade)
                if 0 <= grade_value <= 100:
                    submissions[submission_id]['grade'] = grade_value
                    submissions[submission_id]['feedback'] = feedback
                    submissions[submission_id]['graded_at'] = datetime.now().isoformat()
                    save_json('submissions.json', submissions)
                    flash('Submission graded successfully!', 'success')
                else:
                    flash('Grade must be between 0 and 100.', 'danger')
            except ValueError:
                flash('Invalid grade value.', 'danger')
        
        return redirect(url_for('grade_submissions', prompt_id=prompt_id))
    
    # Get submissions for this prompt
    prompt_submissions = []
    for sub_id, sub in submissions.items():
        if sub['prompt_id'] == prompt_id:
            student_info = users.get(sub['student_id'], {})
            prompt_submissions.append({
                'id': sub_id,
                'student_username': sub['student_id'],
                'student_grade': student_info.get('grade', 'N/A'),
                'response': sub['response'],
                'grade': sub.get('grade'),
                'feedback': sub.get('feedback', ''),
                'submitted_at': sub['submitted_at']
            })
    
    # Sort by submission date
    prompt_submissions.sort(key=lambda x: x['submitted_at'], reverse=True)
    
    if not prompt_submissions:
        flash('No submissions found for this prompt yet.', 'info')
    
    return render_template('grade_submissions.html', 
                         prompt=prompt, 
                         submissions=prompt_submissions)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    users = load_json('users.json')
    user = users.get(session['user_id'])
    
    if user['role'] != 'student':
        return redirect(url_for('teacher_dashboard'))
    
    prompts = load_json('prompts.json')
    submissions = load_json('submissions.json')
    
    # Get prompts for student's grade level
    available_prompts = []
    for prompt_id, prompt in prompts.items():
        if prompt['grade_level'] == user['grade']:
            # Check if student has already submitted
            has_submitted = False
            submission_data = None
            for sub_id, sub in submissions.items():
                if sub['prompt_id'] == prompt_id and sub['student_id'] == session['user_id']:
                    has_submitted = True
                    submission_data = sub
                    break
            
            available_prompts.append({
                'id': prompt_id,
                'title': prompt['title'],
                'description': prompt['description'],
                'has_submitted': has_submitted,
                'submission': submission_data
            })
    
    return render_template('student_dashboard.html', 
                         prompts=available_prompts,
                         user=user)

@app.route('/student/submit/<prompt_id>', methods=['POST'])
@login_required
def submit_response(prompt_id):
    users = load_json('users.json')
    user = users.get(session['user_id'])
    
    if user['role'] != 'student':
        flash('Only students can submit responses.', 'danger')
        return redirect(url_for('index'))
    
    prompts = load_json('prompts.json')
    submissions = load_json('submissions.json')
    
    prompt = prompts.get(prompt_id)
    if not prompt:
        flash('Prompt not found.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    response = request.form.get('response', '').strip()
    
    if not response:
        flash('Response cannot be empty.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    # Check if already submitted
    for sub_id, sub in submissions.items():
        if sub['prompt_id'] == prompt_id and sub['student_id'] == session['user_id']:
            flash('You have already submitted a response to this prompt.', 'warning')
            return redirect(url_for('student_dashboard'))
    
    submission_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}"
    
    submissions[submission_id] = {
        'id': submission_id,
        'prompt_id': prompt_id,
        'student_id': session['user_id'],
        'response': response,
        'submitted_at': datetime.now().isoformat(),
        'grade': None,
        'feedback': ''
    }
    
    save_json('submissions.json', submissions)
    flash('Response submitted successfully!', 'success')
    return redirect(url_for('student_dashboard'))

@app.route('/student/history')
@login_required
def student_history():
    users = load_json('users.json')
    user = users.get(session['user_id'])
    
    if user['role'] != 'student':
        flash('Only students can view submission history.', 'warning')
        return redirect(url_for('teacher_dashboard'))
    
    prompts = load_json('prompts.json')
    submissions = load_json('submissions.json')
    
    # Get all submissions for this student
    student_submissions = []
    for sub_id, sub in submissions.items():
        if sub['student_id'] == session['user_id']:
            prompt = prompts.get(sub['prompt_id'])
            if prompt:
                student_submissions.append({
                    'id': sub_id,
                    'prompt_title': prompt['title'],
                    'prompt_description': prompt['description'],
                    'response': sub['response'],
                    'grade': sub.get('grade'),
                    'feedback': sub.get('feedback', ''),
                    'submitted_at': sub['submitted_at'],
                    'graded_at': sub.get('graded_at')
                })
    
    # Sort by submission date (most recent first)
    student_submissions.sort(key=lambda x: x['submitted_at'], reverse=True)
    
    # Calculate statistics
    total_submissions = len(student_submissions)
    graded_count = sum(1 for s in student_submissions if s['grade'] is not None)
    
    avg_grade = None
    if graded_count > 0:
        total_grade = sum(s['grade'] for s in student_submissions if s['grade'] is not None)
        avg_grade = round(total_grade / graded_count, 2)
    
    stats = {
        'total': total_submissions,
        'graded': graded_count,
        'pending': total_submissions - graded_count,
        'average': avg_grade
    }
    
    return render_template('student_history.html', 
                         submissions=student_submissions, 
                         stats=stats,
                         user=user)

@app.route('/leaderboard')
@login_required
def leaderboard():
    users = load_json('users.json')
    submissions = load_json('submissions.json')
    
    # Calculate average scores for each student
    student_scores = {}
    
    for sub_id, sub in submissions.items():
        if sub.get('grade') is not None:
            student_id = sub['student_id']
            if student_id not in student_scores:
                student_scores[student_id] = {
                    'grades': [],
                    'username': student_id,
                    'grade_level': users.get(student_id, {}).get('grade', 'N/A')
                }
            student_scores[student_id]['grades'].append(sub['grade'])
    
    # Calculate averages
    leaderboard_data = []
    for student_id, data in student_scores.items():
        if data['grades']:
            avg_score = sum(data['grades']) / len(data['grades'])
            leaderboard_data.append({
                'username': data['username'],
                'grade_level': data['grade_level'],
                'avg_score': round(avg_score, 2),
                'num_submissions': len(data['grades'])
            })
    
    # Sort by average score
    leaderboard_data.sort(key=lambda x: x['avg_score'], reverse=True)
    
    # Add ranking
    for i, student in enumerate(leaderboard_data):
        student['rank'] = i + 1
    
    return render_template('leaderboard.html', leaderboard=leaderboard_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)