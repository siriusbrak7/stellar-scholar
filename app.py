# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
import json
import os
from datetime import datetime, timedelta
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
            
            # Create new user with proper grade handling
            user_data = {
                'username': username,
                'password_hash': generate_password_hash(password),
                'role': role,
                'approval_status': 'pending',  # NEW - requires admin approval
                'created_at': datetime.now().isoformat()
            }

            # Only add grade for students
            if role == 'student' and grade:
                user_data['grade'] = grade

            # Add security questions for students
            if role == 'student':
                security_question = request.form.get('security_question')
                security_answer = request.form.get('security_answer')
                if security_question and security_answer:
                    user_data['security_question'] = security_question
                    user_data['security_answer_hash'] = generate_password_hash(security_answer.lower().strip())

            # Insert into Supabase
            result = supabase.table('users').insert(user_data).execute()
            
            if result.data:
                flash('Registration successful! Please wait for admin approval.', 'success')
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
                # NEW: Check if user is approved
                if user.get('approval_status') != 'approved':
                    flash('Your account is pending admin approval. Please wait for activation.', 'warning')
                    return render_template('login.html')
                
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

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return render_template('forgot_password.html')
        
        try:
            # Check if user exists and has security question
            user_response = supabase.table('users').select('*').eq('username', username).execute()
            user = user_response.data[0] if user_response.data else None
            
            if user and user.get('security_question'):
                # Store username in session for verification
                session['reset_username'] = username
                return render_template('security_question.html', 
                                    question=user['security_question'],
                                    username=username)
            else:
                # Don't reveal if user exists for security
                flash('If that username exists and has security questions set, you will be redirected.', 'info')
                return redirect(url_for('forgot_password'))
                
        except Exception as e:
            logger.error(f"Password reset error: {e}")
            flash('Error processing reset request.', 'danger')
    
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        # Verify token is valid and not expired
        response = supabase.table('users').select('*').eq('reset_token', token).execute()
        user = response.data[0] if response.data else None
        
        if not user or datetime.fromisoformat(user['reset_token_expiry']) < datetime.now():
            flash('Invalid or expired reset link.', 'danger')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            new_password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            if not new_password or not confirm_password:
                flash('Please fill in all fields.', 'danger')
                return render_template('reset_password.html', token=token)
            
            if new_password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return render_template('reset_password.html', token=token)
            
            # Update password and clear reset token
            supabase.table('users').update({
                'password_hash': generate_password_hash(new_password),
                'reset_token': None,
                'reset_token_expiry': None
            }).eq('reset_token', token).execute()
            
            flash('Password reset successfully! Please login with your new password.', 'success')
            return redirect(url_for('login'))
        
        return render_template('reset_password.html', token=token)
        
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        flash('Error resetting password.', 'danger')
        return redirect(url_for('forgot_password'))

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get filters from query parameters
        grade_filter = request.args.get('grade', 'all')
        category_filter = request.args.get('category', 'all')
        
        # Get all prompts from Supabase (used to derive available filters)
        prompts_response = supabase.table('prompts').select('*').order('created_at', desc=True).execute()
        all_prompts = prompts_response.data if prompts_response.data else []
        
        # Build available grades and categories from full prompt set (for filter buttons)
        unique_grades = sorted(list({p['grade_level'] for p in all_prompts if p.get('grade_level')}))
        unique_categories = sorted(list({p.get('category', 'general') for p in all_prompts if p.get('category') is not None}))
        
        # Apply grade & category filters to the prompts shown on the dashboard
        filtered_prompts = all_prompts
        if grade_filter != 'all':
            filtered_prompts = [p for p in filtered_prompts if p.get('grade_level') == grade_filter]
        if category_filter != 'all':
            filtered_prompts = [p for p in filtered_prompts if (p.get('category') or 'general') == category_filter]
        
        prompts = {prompt['id']: prompt for prompt in filtered_prompts}
        
        # Get all submissions
        submissions_response = supabase.table('submissions').select('*').execute()
        submissions = submissions_response.data if submissions_response.data else []
        
        # Get all users (for analytics and student progress)
        users_response = supabase.table('users').select('*').execute()
        users_data = users_response.data if users_response.data else []
        
        # Count submissions per prompt (only for prompts currently shown)
        prompt_stats = {}
        for prompt_id in prompts:
            prompt_stats[prompt_id] = {
                'total': 0,
                'graded': 0
            }
        for sub in submissions:
            pid = sub.get('prompt_id')
            if pid in prompt_stats:
                prompt_stats[pid]['total'] += 1
                if sub.get('grade') is not None:
                    prompt_stats[pid]['graded'] += 1
        
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
            if user.get('role') == 'student':
                student_grade = user.get('grade')
                
                # Prompts for this student's grade (use ALL prompts to compute expected work)
                grade_prompts = [p for p in all_prompts if p.get('grade_level') == student_grade]
                total_prompts = len(grade_prompts)
                
                if total_prompts > 0:
                    # Count submissions for this student across all prompts
                    student_subs = [s for s in submissions if s.get('student_id') == user.get('username')]
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

        # If no student progress was collected, ensure defaults are present
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
                student_id = sub.get('student_id')
                if student_id not in student_scores:
                    user_response = supabase.table('users').select('grade').eq('username', student_id).execute()
                    grade_level = user_response.data[0]['grade'] if user_response.data else 'N/A'
                    
                    student_scores[student_id] = {
                        'grades': [],
                        'username': student_id,
                        'grade_level': grade_level
                    }
                student_scores[student_id]['grades'].append(sub.get('grade'))
        
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
        
        # Render template with new category filter context
        return render_template('teacher_dashboard.html', 
                             prompts=prompts, 
                             prompt_stats=prompt_stats,
                             top_students=top_students,
                             current_grade_filter=grade_filter,
                             current_category_filter=category_filter,
                             available_grades=unique_grades,
                             available_categories=unique_categories,
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
        category = request.form.get('category', 'general')
        due_date_str = request.form.get('due_date', '').strip()

        if not title or not description or not grade_level:
            flash('All fields are required.', 'danger')
            return render_template('create_prompt.html')

        try:
            prompt_id = f"prompt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Process due date
            due_date = None
            if due_date_str:
                try:
                    due_dt = datetime.fromisoformat(due_date_str)
                    due_date = due_dt.isoformat()
                except Exception:
                    flash('Invalid due date format. Please provide a valid date/time.', 'danger')
                    return render_template('create_prompt.html')
            
            prompt_data = {
                'id': prompt_id,
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'category': category,
                'due_date': due_date,
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
            category = request.form.get('category', 'general')
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
                'category': category,
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

@app.route('/teacher/students')
@teacher_required
def manage_students():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get all students
        users_response = supabase.table('users').select('*').eq('role', 'student').execute()
        students = users_response.data if users_response.data else []
        
        # Get submission counts for each student
        submissions_response = supabase.table('submissions').select('*').execute()
        submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate student statistics
        student_stats = {}
        for student in students:
            student_subs = [s for s in submissions if s['student_id'] == student['username']]
            graded_subs = [s for s in student_subs if s.get('grade') is not None]
            
            student_stats[student['username']] = {
                'total_submissions': len(student_subs),
                'graded_submissions': len(graded_subs),
                'average_grade': sum(s['grade'] for s in graded_subs) / len(graded_subs) if graded_subs else 0
            }
        
        return render_template('manage_students.html', 
                             students=students, 
                             student_stats=student_stats)
                             
    except Exception as e:
        logger.error(f"Manage students error: {e}")
        flash('Error loading student management.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_student/<username>', methods=['POST'])
@teacher_required
def delete_student(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('manage_students'))
    
    try:
        # First delete student's submissions
        submissions_result = supabase.table('submissions').delete().eq('student_id', username).execute()
        
        # Then delete the student user
        user_result = supabase.table('users').delete().eq('username', username).execute()
        
        if user_result.data:
            flash(f'Student {username} and their submissions have been deleted.', 'success')
        else:
            flash('Student not found or already deleted.', 'warning')
            
    except Exception as e:
        logger.error(f"Delete student error: {e}")
        flash('Error deleting student.', 'danger')
    
    return redirect(url_for('manage_students'))

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
        
        # Get prompts for student's grade level - ORDER BY created_at DESC (NEWEST FIRST)
        prompts_response = supabase.table('prompts').select('*').eq('grade_level', user['grade']).order('created_at', desc=True).execute()
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
                'submission': submission_data,
                'due_date': prompt.get('due_date'),
                'category': prompt.get('category', 'general')
            })
        
        return render_template('student_dashboard.html', 
                             prompts=available_prompts,
                             user=user,
                             now=datetime.now())

    except Exception as e:
        logger.error(f"Student dashboard error: {e}")
        flash('Error loading dashboard.', 'danger')
        return redirect(url_for('index'))

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
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))
        
        response_text = request.form.get('response', '').strip()
        
        if not response_text:
            flash('Response cannot be empty.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Check if already submitted
        existing_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).eq('student_id', session['user_id']).execute()
        
        if existing_response.data:
            flash('You have already submitted a response to this prompt.', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # Create submission
        submission_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}"
        submission_data = {
            'id': submission_id,
            'prompt_id': prompt_id,
            'student_id': session['user_id'],
            'response': response_text,
            'submitted_at': datetime.now().isoformat()
        }
        
        result = supabase.table('submissions').insert(submission_data).execute()
        
        if result.data:
            flash('Response submitted successfully!', 'success')
        else:
            flash('Failed to submit response.', 'danger')
            
    except Exception as e:
        logger.error(f"Submit response error: {e}")
        flash('Error submitting response.', 'danger')
    
    return redirect(url_for('student_dashboard'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
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
        return redirect(url_for('student_dashboard'))

@app.route('/student/view_feedback/<submission_id>')
@login_required
def view_feedback(submission_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get submission
        submission_response = supabase.table('submissions').select('*').eq('id', submission_id).execute()
        submission = submission_response.data[0] if submission_response.data else None
        
        if not submission:
            flash('Submission not found.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Check if this submission belongs to the current user
        if submission['student_id'] != session['user_id']:
            flash('Access denied.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Get prompt details
        prompt_response = supabase.table('prompts').select('*').eq('id', submission['prompt_id']).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        return render_template('view_feedback.html', 
                             submission=submission, 
                             prompt=prompt)
        
    except Exception as e:
        logger.error(f"View feedback error: {e}")
        flash('Error loading feedback.', 'danger')
        return redirect(url_for('student_dashboard'))
    
def admin_required(f):
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
            
            if not user or not user.get('is_admin'):
                flash('Admin access required.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Admin check error: {e}")
            flash('Error verifying admin permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get pending registrations (new users waiting approval)
        pending_users = supabase.table('users').select('*').eq('approval_status', 'pending').execute()
        
        # Get all users for management
        all_users = supabase.table('users').select('*').order('created_at', desc=True).execute()
        
        return render_template('admin_dashboard.html',
                             pending_users=pending_users.data if pending_users.data else [],
                             all_users=all_users.data if all_users.data else [])
    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        flash('Error loading admin dashboard.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
@app.route('/admin/approve_user/<username>', methods=['POST'])
@admin_required
def approve_user(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Update user approval status to 'approved'
        result = supabase.table('users').update({'approval_status': 'approved'}).eq('username', username).execute()
        
        if result.data:
            flash(f'✅ User {username} has been approved successfully!', 'success')
        else:
            flash('User not found.', 'warning')
    except Exception as e:
        logger.error(f"Approve user error: {e}")
        flash('Error approving user.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_user/<username>', methods=['POST'])
@admin_required
def reject_user(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Update user approval status to 'rejected'
        result = supabase.table('users').update({'approval_status': 'rejected'}).eq('username', username).execute()
        
        if result.data:
            flash(f'❌ User {username} has been rejected.', 'success')
        else:
            flash('User not found.', 'warning')
    except Exception as e:
        logger.error(f"Reject user error: {e}")
        flash('Error rejecting user.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

# Add this debug route BEFORE the final if __name__ block
@app.route('/debug-token/<username>')
def debug_token(username):
    supabase = get_supabase()
    if not supabase:
        return "No database connection"
    
    try:
        user_response = supabase.table('users').select('reset_token, reset_token_expiry, username').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user:
            return f"""
            <h3>Token Debug for: {user['username']}</h3>
            <p><strong>Reset Token:</strong> {user.get('reset_token', 'None')}</p>
            <p><strong>Token Expiry:</strong> {user.get('reset_token_expiry', 'None')}</p>
            <p><strong>Current Time:</strong> {datetime.now().isoformat()}</p>
            """
        else:
            return "User not found"
    except Exception as e:
        return f"Error: {e}"
    
@app.route('/verify-security', methods=['POST'])
def verify_security():
    username = request.form.get('username')
    
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        user_response = supabase.table('users').select('*').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user and user.get('security_question'):
            # Store username in session for verification
            session['reset_username'] = username
            return render_template('security_question.html', 
                                question=user['security_question'],
                                username=username)
        else:
            flash('User not found or no security question set.', 'danger')
            return redirect(url_for('forgot_password'))
            
    except Exception as e:
        logger.error(f"Security question error: {e}")
        flash('Error verifying user.', 'danger')
        return redirect(url_for('forgot_password'))

@app.route('/reset-with-answer', methods=['POST'])
def reset_with_answer():
    answer = request.form.get('security_answer', '').strip().lower()
    username = session.get('reset_username')
    
    if not username:
        return redirect(url_for('forgot_password'))
    
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        user_response = supabase.table('users').select('*').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user and check_password_hash(user['security_answer_hash'], answer):
            # Answer correct - generate reset token
            import secrets
            reset_token = secrets.token_urlsafe(32)
            supabase.table('users').update({
                'reset_token': reset_token,
                'reset_token_expiry': (datetime.now() + timedelta(hours=1)).isoformat()
            }).eq('username', username).execute()
            
            session.pop('reset_username', None)
            return redirect(url_for('reset_password', token=reset_token))
        else:
            flash('Incorrect security answer.', 'danger')
            return redirect(url_for('forgot_password'))
            
    except Exception as e:
        logger.error(f"Security answer error: {e}")
        flash('Error verifying answer.', 'danger')
        return redirect(url_for('forgot_password'))

if __name__ == '__main__':
    app.run(debug=True)