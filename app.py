from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
import json
import os
from datetime import datetime
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
import logging

app = Flask(__name__)
app.config.from_object(Config)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
def get_supabase():
    """Initialize and return Supabase client"""
    try:
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        
        if not url or not key:
            logger.error("Missing Supabase environment variables")
            return None
            
        return create_client(url, key)
    except Exception as e:
        logger.error(f"Error initializing Supabase: {e}")
        return None

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
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            # Get user from Supabase
            response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = response.data[0] if response.data else None
            
            if not user or user['role'] != 'teacher':
                flash('Access denied. Teachers only.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error checking teacher role: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('register.html')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role')
        grade = request.form.get('grade') if role == 'student' else None
        
        # Validation
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('register.html')
        
        if role == 'student' and not grade:
            flash('Please select your grade level.', 'danger')
            return render_template('register.html')
        
        try:
            # Check if username already exists
            response = supabase.table('users').select('username').eq('username', username).execute()
            if response.data:
                flash('Username already exists. Please choose another.', 'danger')
                return render_template('register.html')
            
            # Create new user
            user_data = {
                'username': username,
                'password_hash': generate_password_hash(password),
                'role': role,
                'grade': grade,
                'created_at': datetime.now().isoformat()
            }
            
            # Insert into Supabase
            result = supabase.table('users').insert(user_data).execute()
            
            if result.data:
                flash('Registration successful! Please log in.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Registration failed. Please try again.', 'danger')
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            flash('Registration error. Please try again.', 'danger')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('login.html')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        try:
            # Get user from Supabase
            response = supabase.table('users').select('*').eq('username', username).execute()
            user = response.data[0] if response.data else None
            
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
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            flash('Login error. Please try again.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get grade filter from query parameter
        grade_filter = request.args.get('grade', 'all')
        
        # Get all prompts
        prompts_response = supabase.table('prompts').select('*').execute()
        all_prompts = prompts_response.data if prompts_response.data else []
        
        # Apply grade filter
        if grade_filter != 'all':
            prompts_data = [p for p in all_prompts if p['grade_level'] == grade_filter]
        else:
            prompts_data = all_prompts
        
        prompts = {prompt['id']: prompt for prompt in prompts_data}
        
        # Get all submissions
        submissions_response = supabase.table('submissions').select('*').execute()
        submissions = submissions_response.data if submissions_response.data else []
        
        # Get all users (for analytics)
        users_response = supabase.table('users').select('*').execute()
        users_data = users_response.data if users_response.data else []
        
        # Count submissions per prompt
        prompt_stats = {}
        for prompt_id in prompts:
            prompt_stats[prompt_id] = {
                'total': 0,
                'graded': 0
            }
            for sub in submissions:
                if sub['prompt_id'] == prompt_id:
                    prompt_stats[prompt_id]['total'] += 1
                    if sub.get('grade') is not None:
                        prompt_stats[prompt_id]['graded'] += 1
        
        # Get unique grades for filter buttons
        unique_grades = sorted(list(set([p['grade_level'] for p in all_prompts])))
        
        # STUDENT PROGRESS TRACKING
        student_progress = {}
        class_analytics = {
            'total_students': 0,
            'active_students': 0,
            'total_submissions': 0,
            'average_completion_rate': 0,
            'average_grade': 0,
            'grade_breakdown': {}
        }
        
        # Calculate student progress and class analytics
        for user in users_data:
            if user['role'] == 'student':
                student_grade = user['grade']
                
                # Get prompts for this student's grade
                grade_prompts = [p for p in all_prompts if p['grade_level'] == student_grade]
                total_prompts = len(grade_prompts)
                
                if total_prompts > 0:
                    # Count submissions for this student
                    student_subs = [s for s in submissions if s['student_id'] == user['username']]
                    submitted_count = len(student_subs)
                    graded_subs = [s for s in student_subs if s.get('grade') is not None]
                    
                    completion_rate = (submitted_count / total_prompts) * 100
                    avg_grade = sum(s['grade'] for s in graded_subs) / len(graded_subs) if graded_subs else 0
                    
                    student_progress[user['username']] = {
                        'username': user['username'],
                        'grade_level': student_grade,
                        'completed_prompts': submitted_count,
                        'total_prompts': total_prompts,
                        'completion_rate': round(completion_rate, 1),
                        'average_grade': round(avg_grade, 1) if graded_subs else 'N/A',
                        'graded_count': len(graded_subs)
                    }
                    
                    # Update class analytics
                    class_analytics['total_students'] += 1
                    if submitted_count > 0:
                        class_analytics['active_students'] += 1
                    
                    class_analytics['total_submissions'] += submitted_count
                    
                    # Update grade breakdown
                    if student_grade not in class_analytics['grade_breakdown']:
                        class_analytics['grade_breakdown'][student_grade] = {
                            'students': 0,
                            'active': 0,
                            'completion_rate': 0
                        }
                    
                    class_analytics['grade_breakdown'][student_grade]['students'] += 1
                    if submitted_count > 0:
                        class_analytics['grade_breakdown'][student_grade]['active'] += 1

        # If no student progress was collected, initialize empty structures to avoid template errors
        if not student_progress:
            student_progress = {}
            class_analytics = {
                'total_students': 0,
                'active_students': 0,
                'total_submissions': 0,
                'average_completion_rate': 0,
                'average_grade': 0,
                'grade_breakdown': {}
            }

        # Calculate overall averages
        if class_analytics['total_students'] > 0:
            # Avoid division by zero when no student progress entries exist
            if student_progress and len(student_progress) > 0:
                completion_rates = [s['completion_rate'] for s in student_progress.values()]
                if len(completion_rates) > 0:
                    class_analytics['average_completion_rate'] = round(sum(completion_rates) / len(completion_rates), 1)
                else:
                    class_analytics['average_completion_rate'] = 0
            else:
                class_analytics['average_completion_rate'] = 0
            
            grades = [s['average_grade'] for s in student_progress.values() if s['average_grade'] != 'N/A']
            if grades:
                class_analytics['average_grade'] = round(sum(grades) / len(grades), 1)
        
        # Get top students for leaderboard preview
        top_students = []
        student_scores = {}
        
        for sub in submissions:
            if sub.get('grade') is not None:
                student_id = sub['student_id']
                if student_id not in student_scores:
                    user_response = supabase.table('users').select('grade').eq('username', student_id).execute()
                    grade_level = user_response.data[0]['grade'] if user_response.data else 'N/A'
                    
                    student_scores[student_id] = {
                        'grades': [],
                        'username': student_id,
                        'grade_level': grade_level
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
        top_students = top_students[:5]
        
        return render_template('teacher_dashboard.html', 
                             prompts=prompts, 
                             prompt_stats=prompt_stats,
                             top_students=top_students,
                             current_grade_filter=grade_filter,
                             available_grades=unique_grades,
                             student_progress=student_progress,
                             class_analytics=class_analytics)
                             
    except Exception as e:
        logger.error(f"Teacher dashboard error: {e}")
        flash('Error loading dashboard.', 'danger')
        return redirect(url_for('index'))

@app.route('/teacher/create_prompt', methods=['GET', 'POST'])
@teacher_required
def create_prompt():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return render_template('create_prompt.html')
        
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        grade_level = request.form.get('grade_level')
        due_date_str = request.form.get('due_date', '').strip()
        due_date_iso = None
        if due_date_str:
            try:
                # Accept ISO-like input from datetime-local (e.g. 2023-08-01T14:30)
                due_dt = datetime.fromisoformat(due_date_str)
                due_date_iso = due_dt.isoformat()
            except Exception:
                flash('Invalid due date format. Please provide a valid date/time.', 'danger')
                return render_template('create_prompt.html')
        
        if not title or not description or not grade_level:
            flash('All fields are required.', 'danger')
            return render_template('create_prompt.html')
        
        try:
            prompt_id = f"prompt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            prompt_data = {
                'id': prompt_id,
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'due_date': due_date_iso,
                'created_by': session['user_id'],
                'created_at': datetime.now().isoformat()
            }
            
            # Insert into Supabase
            result = supabase.table('prompts').insert(prompt_data).execute()
            
            if result.data:
                flash('Prompt created successfully!', 'success')
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Failed to create prompt.', 'danger')
                
        except Exception as e:
            logger.error(f"Create prompt error: {e}")
            flash('Error creating prompt.', 'danger')
    
    return render_template('create_prompt.html')

@app.route('/teacher/edit_prompt/<prompt_id>', methods=['GET', 'POST'])
@teacher_required
def edit_prompt(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get the current prompt
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Prompt not found.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        # Check if user owns this prompt
        if prompt['created_by'] != session['user_id']:
            flash('You can only edit prompts you created.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            grade_level = request.form.get('grade_level')
            due_date_str = request.form.get('due_date')
            
            if not title or not description or not grade_level:
                flash('All fields are required.', 'danger')
                return render_template('edit_prompt.html', prompt=prompt)
            
            # Process due date
            due_date = None
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                except ValueError:
                    flash('Invalid due date format.', 'danger')
                    return render_template('edit_prompt.html', prompt=prompt)
            
            # Update prompt in Supabase
            update_data = {
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'due_date': due_date.isoformat() if due_date else None,
                'updated_at': datetime.now().isoformat()
            }
            
            result = supabase.table('prompts').update(update_data).eq('id', prompt_id).execute()
            
            if result.data:
                flash('Prompt updated successfully!', 'success')
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Failed to update prompt.', 'danger')
        
        return render_template('edit_prompt.html', prompt=prompt)
        
    except Exception as e:
        logger.error(f"Edit prompt error: {e}")
        flash('Error editing prompt.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_prompt/<prompt_id>', methods=['POST'])
@teacher_required
def delete_prompt(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # First, check if there are any submissions for this prompt
        submissions_response = supabase.table('submissions').select('id').eq('prompt_id', prompt_id).execute()
        
        if submissions_response.data:
            flash('Cannot delete prompt - students have already submitted responses to it.', 'warning')
            return redirect(url_for('teacher_dashboard'))
        
        # Delete the prompt from Supabase
        result = supabase.table('prompts').delete().eq('id', prompt_id).execute()
        
        if result.data:
            flash('Prompt deleted successfully!', 'success')
        else:
            flash('Prompt not found or already deleted.', 'warning')
            
    except Exception as e:
        logger.error(f"Delete prompt error: {e}")
        flash('Error deleting prompt.', 'danger')
    
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/grade/<prompt_id>', methods=['GET', 'POST'])
@teacher_required
def grade_submissions(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get prompt
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Prompt not found.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        if request.method == 'POST':
            submission_id = request.form.get('submission_id')
            grade = request.form.get('grade')
            feedback = request.form.get('feedback', '').strip()
            
            if submission_id:
                try:
                    grade_value = float(grade) if grade else None
                    if grade_value is not None and (grade_value < 0 or grade_value > 100):
                        flash('Grade must be between 0 and 100.', 'danger')
                    else:
                        # Update submission in Supabase
                        update_data = {}
                        if grade_value is not None:
                            update_data['grade'] = grade_value
                        if feedback:
                            update_data['feedback'] = feedback
                        update_data['graded_at'] = datetime.now().isoformat()
                        
                        result = supabase.table('submissions').update(update_data).eq('id', submission_id).execute()
                        
                        if result.data:
                            flash('Submission graded successfully!', 'success')
                        else:
                            flash('Failed to grade submission.', 'danger')
                except ValueError:
                    flash('Invalid grade value.', 'danger')
            
            return redirect(url_for('grade_submissions', prompt_id=prompt_id))
        
        # Get submissions for this prompt with student info
        submissions_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).execute()
        prompt_submissions = []
        
        for sub in submissions_response.data:
            # Get student info
            user_response = supabase.table('users').select('grade').eq('username', sub['student_id']).execute()
            student_grade = user_response.data[0]['grade'] if user_response.data else 'N/A'
            
            prompt_submissions.append({
                'id': sub['id'],
                'student_username': sub['student_id'],
                'student_grade': student_grade,
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
                             
    except Exception as e:
        logger.error(f"Grade submissions error: {e}")
        flash('Error loading submissions.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or user['role'] != 'student':
            return redirect(url_for('teacher_dashboard'))
        
        # Get prompts for student's grade level
        prompts_response = supabase.table('prompts').select('*').eq('grade_level', user['grade']).execute()
        prompts_data = prompts_response.data if prompts_response.data else []
        
        # Get student's submissions
        submissions_response = supabase.table('submissions').select('*').eq('student_id', session['user_id']).execute()
        submissions_data = submissions_response.data if submissions_response.data else []
        
        available_prompts = []
        for prompt in prompts_data:
            # Check if student has already submitted
            has_submitted = False
            submission_data = None
            for sub in submissions_data:
                if sub['prompt_id'] == prompt['id']:
                    has_submitted = True
                    submission_data = sub
                    break
            
            available_prompts.append({
                'id': prompt['id'],
                'title': prompt['title'],
                'description': prompt['description'],
                'has_submitted': has_submitted,
                'submission': submission_data
            })
        
        return render_template('student_dashboard.html', 
                             prompts=available_prompts,
                             user=user)
                             
    except Exception as e:
        logger.error(f"Student dashboard error: {e}")
        flash('Error loading dashboard.', 'danger')
        return redirect(url_for('index'))

@app.route('/student/submit/<prompt_id>', methods=['POST'])
@login_required
def submit_response(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or user['role'] != 'student':
            flash('Only students can submit responses.', 'danger')
            return redirect(url_for('index'))
        
        # Get prompt
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Prompt not found.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        response = request.form.get('response', '').strip()
        
        if not response:
            flash('Response cannot be empty.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Check if already submitted
        existing_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).eq('student_id', session['user_id']).execute()
        if existing_response.data:
            flash('You have already submitted a response to this prompt.', 'warning')
            return redirect(url_for('student_dashboard'))
        
        submission_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}"
        
        submission_data = {
            'id': submission_id,
            'prompt_id': prompt_id,
            'student_id': session['user_id'],
            'response': response,
            'submitted_at': datetime.now().isoformat(),
            'grade': None,
            'feedback': ''
        }
        
        # Insert into Supabase
        result = supabase.table('submissions').insert(submission_data).execute()
        
        if result.data:
            flash('Response submitted successfully!', 'success')
        else:
            flash('Failed to submit response.', 'danger')
            
        return redirect(url_for('student_dashboard'))
        
    except Exception as e:
        logger.error(f"Submit response error: {e}")
        flash('Error submitting response.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/student/history')
@login_required
def student_history():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or user['role'] != 'student':
            flash('Only students can view submission history.', 'warning')
            return redirect(url_for('teacher_dashboard'))
        
        # Get all submissions for this student with prompt info
        submissions_response = supabase.table('submissions').select('*').eq('student_id', session['user_id']).execute()
        student_submissions = []
        
        for sub in submissions_response.data:
            # Get prompt info
            prompt_response = supabase.table('prompts').select('*').eq('id', sub['prompt_id']).execute()
            prompt = prompt_response.data[0] if prompt_response.data else None
            
            if prompt:
                student_submissions.append({
                    'id': sub['id'],
                    'prompt_title': prompt['title'],
                    'prompt_description': prompt['description'],
                    'response': sub['response'],
                    'grade': sub.get('grade'),
                    'feedback': sub.get('feedback', ''),
                    'submitted_at': sub['submitted_at'],
                    'graded_at': sub.get('graded_at')
                })

        # FINAL TEST: Data persistence check - Brakatu 11:07
        
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
                             
    except Exception as e:
        logger.error(f"Student history error: {e}")
        flash('Error loading submission history.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get grade filter from query parameter
        grade_filter = request.args.get('grade', 'all')
        
        # Get all users
        users_response = supabase.table('users').select('*').execute()
        users_data = {user['username']: user for user in users_response.data} if users_response.data else {}
        
        # Get all prompts
        prompts_response = supabase.table('prompts').select('*').execute()
        prompts_data = prompts_response.data if prompts_response.data else []
        
        # Get all submissions with grades
        submissions_response = supabase.table('submissions').select('*').not_.is_('grade', 'null').execute()
        graded_submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate average scores for each student - FAIR CALCULATION
        student_scores = {}
        
        for student_username, user_data in users_data.items():
            if user_data['role'] == 'student':
                student_grade = user_data['grade']
                
                # Get all prompts for this student's grade level
                grade_prompts = [p for p in prompts_data if p['grade_level'] == student_grade]
                total_prompts = len(grade_prompts)
                
                if total_prompts > 0:
                    # Initialize student data
                    student_scores[student_username] = {
                        'grades': [],  # Actual grades received
                        'possible_grades': [],  # Including zeros for missing submissions
                        'username': student_username,
                        'grade_level': student_grade,
                        'total_prompts': total_prompts,
                        'submitted_prompts': 0
                    }
                    
                    # For each prompt in student's grade level
                    for prompt in grade_prompts:
                        # Find if student submitted to this prompt
                        submission = next((s for s in graded_submissions 
                                         if s['student_id'] == student_username 
                                         and s['prompt_id'] == prompt['id']), None)
                        
                        if submission:
                            # Student submitted and was graded
                            student_scores[student_username]['grades'].append(submission['grade'])
                            student_scores[student_username]['possible_grades'].append(submission['grade'])
                            student_scores[student_username]['submitted_prompts'] += 1
                        else:
                            # Student didn't submit - count as 0 for fair average
                            student_scores[student_username]['possible_grades'].append(0)
        
        # Calculate averages using FAIR calculation (include zeros for missing work)
        leaderboard_data = []
        for student_username, data in student_scores.items():
            if data['possible_grades']:  # Only include students with prompts in their grade
                # FAIR AVERAGE: sum of all grades (including zeros) / total prompts in grade
                fair_avg_score = sum(data['possible_grades']) / len(data['possible_grades'])
                
                leaderboard_data.append({
                    'username': data['username'],
                    'grade_level': data['grade_level'],
                    'avg_score': round(fair_avg_score, 2),
                    'num_submissions': data['submitted_prompts'],
                    'total_prompts': data['total_prompts'],
                    'completion_rate': round((data['submitted_prompts'] / data['total_prompts']) * 100) if data['total_prompts'] > 0 else 0
                })
        
        # Apply grade filter if specified
        if grade_filter != 'all':
            leaderboard_data = [s for s in leaderboard_data if s['grade_level'] == grade_filter]
        
        # Sort by average score (descending)
        leaderboard_data.sort(key=lambda x: x['avg_score'], reverse=True)
        
        # Add ranking
        for i, student in enumerate(leaderboard_data):
            student['rank'] = i + 1
        
        # Get unique grades for filter buttons
        unique_grades = sorted(list(set([s['grade_level'] for s in leaderboard_data])))
        
        return render_template('leaderboard.html', 
                             leaderboard=leaderboard_data,
                             current_grade_filter=grade_filter,
                             available_grades=unique_grades)
        
    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        flash('Error loading leaderboard.', 'danger')
        return redirect(url_for('index'))
    
# Add keep-alive thread to prevent Render spin-down
if 'RENDER' in os.environ:
    def keep_alive():
        """Background thread to prevent auto-spin down"""
        import time
        while True:
            time.sleep(300)  # Run every 5 minutes
            try:
                print(f"🔄 Keep-alive ping at {datetime.now().strftime('%H:%M:%S')}")
            except:
                pass
    
    import threading
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-alive thread started for Render deployment")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)