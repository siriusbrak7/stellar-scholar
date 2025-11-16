# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
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

# ===== ENHANCED DECORATORS =====
def super_admin_required(f):
    """Only for sirius - the platform owner"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] != 'sirius':
            flash('Super admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def school_admin_required(f):
    """For school-level admins (teachers with is_admin=True)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = user_response.data[0] if user_response.data else None
            
            if not user or not user.get('is_admin') or user['role'] != 'teacher':
                flash('School admin access required.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"School admin check error: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

def teacher_required(f):
    """Enhanced to ensure school scoping"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # Super admin should not access teacher dashboard
        if session['user_id'] == 'sirius':
            return redirect(url_for('super_admin_dashboard'))
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = user_response.data[0] if user_response.data else None
            
            if not user or user['role'] != 'teacher':
                flash('Teacher access required.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Teacher check error: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_user_info():
    """Inject user info into all templates"""
    if 'user_id' in session:
        supabase = get_supabase()
        if supabase:
            try:
                user_response = supabase.table('users').select('is_admin, school_id').eq('username', session['user_id']).execute()
                user = user_response.data[0] if user_response.data else None
                if user:
                    return {
                        'is_school_admin': user.get('is_admin', False) and session.get('role') == 'teacher',
                        'user_school_id': user.get('school_id')
                    }
            except Exception as e:
                logger.error(f"Context processor error: {e}")
    
    return {'is_school_admin': False, 'user_school_id': None}

# ===== DATABASE FIX ROUTES =====
@app.route('/fix-schools-table')
def fix_schools_table():
    """Add missing columns to schools table"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # First, let's see what columns actually exist
        test_school = supabase.table('schools').select('*').limit(1).execute()
        if test_school.data:
            existing_columns = list(test_school.data[0].keys())
            return f"""
            <h3>Current Schools Table Columns:</h3>
            <pre>{existing_columns}</pre>
            <p>If 'status' is missing, you need to run this SQL in Supabase:</p>
            <pre>
ALTER TABLE schools ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_person TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_phone TEXT;
            </pre>
            """
        else:
            return "No schools found. Try creating one first."
                
    except Exception as e:
        error_msg = str(e)
        if 'status' in error_msg:
            return """
            <h3>❌ Missing 'status' Column</h3>
            <p>You need to add the 'status' column to your schools table.</p>
            <p>Go to <strong>Supabase → SQL Editor</strong> and run this:</p>
            <pre>
ALTER TABLE schools ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_person TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_phone TEXT;
            </pre>
            <p>Then refresh this page to check.</p>
            """
        return f"Error: {error_msg}"

@app.route('/setup-database')
def setup_database():
    """Check if database is working"""
    supabase = get_supabase()
    if not supabase:
        return "❌ Database connection failed"
    
    try:
        # Test schools table
        schools = supabase.table('schools').select('*').execute()
        # Test users table  
        users = supabase.table('users').select('*').execute()
        
        return f"""
        <h3>✅ Database Connection Working</h3>
        <p>Schools table: {len(schools.data) if schools.data else 0} records</p>
        <p>Users table: {len(users.data) if users.data else 0} records</p>
        <p><strong>Database is ready!</strong></p>
        """
    except Exception as e:
        return f"❌ Database error: {str(e)}"

@app.route('/debug-data')
def debug_data():
    """See all current data"""
    supabase = get_supabase()
    if not supabase:
        return "No database connection"
    
    try:
        schools = supabase.table('schools').select('*').execute()
        users = supabase.table('users').select('username, role, school_id, is_admin, approval_status').execute()
        
        return f"""
        <h3>Current Database Data</h3>
        <h4>Schools ({len(schools.data) if schools.data else 0}):</h4>
        <pre>{schools.data}</pre>
        <h4>Users ({len(users.data) if users.data else 0}):</h4> 
        <pre>{users.data}</pre>
        """
    except Exception as e:
        return f"Error: {str(e)}"

# ===== DEMO SCHOOL SETUP =====
@app.route('/create-demo-school')
def create_demo_school():
    """Quickly create a demo school for testing"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Check if demo school already exists
        existing = supabase.table('schools').select('id, name').eq('name', 'Newel Academy').execute()
        if existing.data:
            return "Demo school already exists!"
        
        # Create demo school - only use columns that definitely exist
        school_data = {
            'id': 'school_demo_academy',
            'name': 'Newel Academy', 
            'created_at': datetime.now().isoformat()
        }
        
        # Try to add status if column exists
        try:
            school_data['status'] = 'active'
        except:
            pass  # Column doesn't exist yet
            
        school_result = supabase.table('schools').insert(school_data).execute()
        
        if school_result.data:
            return """
            <h3>✅ Demo School Created!</h3>
            <p><strong>School Name:</strong> Newel Academy</p>
            <p><strong>School ID:</strong> school_demo_academy</p>
            <p>You can now register teachers and students for this school.</p>
            <a href="/register" class="btn btn-primary">Register Users</a>
            <br><br>
            <small>Note: You may need to <a href="/fix-schools-table">add missing columns</a> for full functionality.</small>
            """
        else:
            return "Failed to create demo school"
            
    except Exception as e:
        return f"Error: {str(e)}<br><br>You may need to <a href='/fix-schools-table'>fix the database schema</a> first."

# ===== MAIN ROUTES =====
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
        security_question = request.form.get('security_question', '').strip()
        security_answer = request.form.get('security_answer', '').strip()

        # Basic validation
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('register.html')

        if role == 'student' and not grade:
            flash('Please select your grade level.', 'danger')
            return render_template('register.html')

        try:
            # Check existing username
            response = supabase.table('users').select('username').eq('username', username).execute()
            if response.data:
                flash('Username already exists. Please choose another.', 'danger')
                return render_template('register.html')

            # Base user data
            user_data = {
                'username': username,
                'password_hash': generate_password_hash(password),
                'role': role,
                'approval_status': 'pending',
                'created_at': datetime.now().isoformat()
            }

            # Add grade if student
            if role == 'student' and grade:
                user_data['grade'] = grade

            # ✅ ADD SECURITY QUESTION FOR ALL USERS (not just students)
            if security_question and security_answer:
                user_data['security_question'] = security_question
                user_data['security_answer_hash'] = generate_password_hash(
                    security_answer.lower().strip()
                )

            # ✅ Add school_id
            school_id = request.form.get('school_id')
            user_data['school_id'] = school_id

            # Insert into database
            result = supabase.table('users').insert(user_data).execute()

            if result.data:
                flash('Registration successful! Please wait for admin approval.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Registration failed. Please try again.', 'danger')

        except Exception as e:
            logger.error(f"Registration error: {e}")
            flash('Registration error. Please try again.', 'danger')

    # GET request — Fetch schools for dropdown
    supabase = get_supabase()
    schools = []
    if supabase:
        try:
            schools_response = supabase.table('schools').select('*').execute()
            schools = schools_response.data if schools_response.data else []
        except Exception as e:
            logger.error(f"Error fetching schools: {e}")
            schools = []

    return render_template('register.html', schools=schools)

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
                flash('If that username exists and has a security question set, you will be redirected to answer it.', 'info')
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
    # GET CURRENT USER FIRST
    user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
    user = user_response.data[0] if user_response.data else None
    
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get filters from query parameters
        grade_filter = request.args.get('grade', 'all')
        category_filter = request.args.get('category', 'all')
        
        # Get all prompts from user's school only - FIXED SYNTAX
        prompts_response = supabase.table('prompts').select('*').eq('school_id', user['school_id']).order('created_at', desc=True).execute()
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
        
        # ✅ GET CURRENT USER FIRST (required for school_id)
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None

        if not user:
            flash("User not found. Please log in again.", "danger")
            return redirect(url_for('logout'))

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
            
            # ✅ Now this works because user is defined
            prompt_data = {
                'id': prompt_id,
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'category': category,
                'due_date': due_date,
                'created_by': session['user_id'],
                'created_at': datetime.now().isoformat(),
                'school_id': user['school_id'],   # <-- FIXED
            }

            result = supabase.table('prompts').insert(prompt_data).execute()
            if result.data:
                flash('Prompt created successfully!', 'success')
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Failed to create prompt.', 'danger')

        except Exception as e:
            logger.error(f"Prompt creation error: {e}")
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
@app.route('/fix-database')
def fix_database():
    """Debug and fix database schema issues"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Check schools table structure
        schools_response = supabase.table('schools').select('*').limit(1).execute()
        print("Schools table:", schools_response.data)
        
        # Check users table structure  
        users_response = supabase.table('users').select('*').limit(1).execute()
        print("Users table:", users_response.data)
        
        return f"""
        <h3>Database Check</h3>
        <p>Schools: {len(schools_response.data) if schools_response.data else 0} records</p>
        <p>Users: {len(users_response.data) if users_response.data else 0} records</p>
        <p>If you see errors above, you need to create the schools table in Supabase.</p>
        """
    except Exception as e:
        return f"Database error: {str(e)}"

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    supabase = get_supabase()
    # GET CURRENT USER FIRST
    user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
    user = user_response.data[0] if user_response.data else None
    
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
@teacher_required
def admin_dashboard():
    """School-scoped admin dashboard for user approvals"""
    supabase = get_supabase()
    user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
    user = user_response.data[0] if user_response.data else None
    
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get pending registrations from user's school only
        pending_users = supabase.table('users').select('*').eq('approval_status', 'pending').eq('school_id', user['school_id']).execute()
        
        # Get all users from user's school only
        all_users = supabase.table('users').select('*').eq('school_id', user['school_id']).order('created_at', desc=True).execute()
        
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

@app.route('/get-hash/<password>')
def get_hash(password):
    return generate_password_hash(password)

@app.route('/school/register', methods=['GET', 'POST'])
def school_register():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('school_register.html')
            
        school_name = request.form.get('school_name', '').strip()
        admin_username = request.form.get('admin_username', '').strip()
        admin_password = request.form.get('admin_password', '').strip()
        admin_email = request.form.get('admin_email', '').strip()
        
        # Debug: Print form data
        print(f"Form data: {school_name}, {admin_username}, {admin_email}")
        
        # Validation
        if not all([school_name, admin_username, admin_password, admin_email]):
            flash('School name, admin username, password and email are required.', 'danger')
            return render_template('school_register.html')
        
        try:
            # Check if admin username already exists
            user_response = supabase.table('users').select('username').eq('username', admin_username).execute()
            if user_response.data:
                flash('Admin username already exists. Please choose another.', 'danger')
                return render_template('school_register.html')
            
            # Check if school name already exists
            school_response = supabase.table('schools').select('name').eq('name', school_name).execute()
            if school_response.data:
                flash('A school with this name already exists.', 'danger')
                return render_template('school_register.html')
            
            # Generate unique school ID
            import secrets
            school_id = f"school_{secrets.token_hex(8)}"
            
            # Create school with PENDING status
            school_data = {
                'id': school_id,
                'name': school_name,
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            }
            
            print(f"Creating school: {school_data}")
            school_result = supabase.table('schools').insert(school_data).execute()
            
            if not school_result.data:
                flash('Failed to create school. Please try again.', 'danger')
                return render_template('school_register.html')
            
            # Create admin account (also pending)
            user_data = {
                'username': admin_username,
                'password_hash': generate_password_hash(admin_password),
                'email': admin_email,
                'role': 'teacher',
                'approval_status': 'pending',
                'school_id': school_id,
                'is_admin': True,
                'created_at': datetime.now().isoformat()
            }
            
            print(f"Creating admin user: {user_data}")
            user_result = supabase.table('users').insert(user_data).execute()
            
            if user_result.data:
                flash('School registration submitted successfully! Your school requires approval from the platform administrator. You will be notified once approved.', 'success')
                return redirect(url_for('index'))
            else:
                # Clean up school if user creation fails
                supabase.table('schools').delete().eq('id', school_id).execute()
                flash('Failed to create admin account. Please try again.', 'danger')
                
        except Exception as e:
            logger.error(f"School registration error: {e}")
            flash(f'Error during school registration: {str(e)}', 'danger')
    
    return render_template('school_register.html')

@app.route('/super/admin/schools')
@super_admin_required
def super_admin_schools():
    """Super admin dashboard for managing schools"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get all schools
        schools_response = supabase.table('schools').select('*').order('created_at', desc=True).execute()
        schools = schools_response.data if schools_response.data else []
        
        # Get stats
        pending_schools = [s for s in schools if s['status'] == 'pending']
        active_schools = [s for s in schools if s['status'] == 'active']
        
        stats = {
            'total_schools': len(schools),
            'pending_schools': len(pending_schools),
            'active_schools': len(active_schools)
        }
        
        return render_template('super_admin_schools.html',
                             schools=schools,
                             stats=stats)
                             
    except Exception as e:
        logger.error(f"Super admin schools error: {e}")
        flash('Error loading school management.', 'danger')
        return redirect(url_for('index'))

@app.route('/super/admin/approve_school/<school_id>', methods=['POST'])
@super_admin_required
def approve_school(school_id):
    """Approve a school and activate its admin"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Update school status
        school_result = supabase.table('schools').update({'status': 'active'}).eq('id', school_id).execute()
        
        # Activate the school admin user
        user_result = supabase.table('users').update({'approval_status': 'approved'}).eq('school_id', school_id).eq('is_admin', True).execute()
        
        if school_result.data and user_result.data:
            flash('School approved successfully! The school admin can now log in.', 'success')
        else:
            flash('Error approving school.', 'danger')
            
    except Exception as e:
        logger.error(f"Approve school error: {e}")
        flash('Error approving school.', 'danger')
    
    return redirect(url_for('super_admin_schools'))

@app.route('/super/admin/reject_school/<school_id>', methods=['POST'])
@super_admin_required
def reject_school(school_id):
    """Reject a school registration"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Delete school and its admin user
        supabase.table('users').delete().eq('school_id', school_id).execute()
        supabase.table('schools').delete().eq('id', school_id).execute()
        
        flash('School registration rejected and removed.', 'success')
            
    except Exception as e:
        logger.error(f"Reject school error: {e}")
        flash('Error rejecting school.', 'danger')
    
    return redirect(url_for('super_admin_schools'))


@app.route('/school/admin/dashboard')
@school_admin_required
def school_admin_dashboard():
    """School admin dashboard for managing their school"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get current user and school
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or not user.get('is_admin'):
            flash('School admin access required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        # Get school information
        school_response = supabase.table('schools').select('*').eq('id', user['school_id']).execute()
        school = school_response.data[0] if school_response.data else None
        
        # Get all users in the school
        users_response = supabase.table('users').select('*').eq('school_id', user['school_id']).execute()
        school_users = users_response.data if users_response.data else []
        
        # Get statistics
        teachers = [u for u in school_users if u['role'] == 'teacher']
        students = [u for u in school_users if u['role'] == 'student']
        pending_users = [u for u in school_users if u.get('approval_status') == 'pending']
        
        stats = {
            'total_teachers': len(teachers),
            'total_students': len(students),
            'pending_approvals': len(pending_users),
            'total_users': len(school_users)
        }
        
        return render_template('school_admin_dashboard.html',
                             school=school,
                             users=school_users,
                             stats=stats)
                             
    except Exception as e:
        logger.error(f"School admin dashboard error: {e}")
        flash('Error loading school admin dashboard.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/school/admin/bulk_import', methods=['GET', 'POST'])
@school_admin_required
def bulk_import_users():
    """Bulk import teachers/students for the school"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('school_admin_dashboard'))
    
    try:
        # Get current user to check admin status and school_id
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or not user.get('is_admin'):
            flash('School admin access required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        if request.method == 'POST':
            import_type = request.form.get('import_type')  # 'teachers' or 'students'
            csv_data = request.form.get('csv_data', '').strip()
            
            if not csv_data:
                flash('Please provide CSV data.', 'danger')
                return render_template('bulk_import.html')
            
            lines = csv_data.split('\n')
            imported_count = 0
            errors = []
            
            for i, line in enumerate(lines[1:], start=2):  # Skip header row
                if not line.strip():
                    continue
                    
                parts = [part.strip() for part in line.split(',')]
                if len(parts) < 3:
                    errors.append(f"Line {i}: Invalid format, expected username,password,email[,grade]")
                    continue
                
                username, password, email = parts[0], parts[1], parts[2]
                grade = parts[3] if len(parts) > 3 and import_type == 'students' else None
                
                # Check if username already exists
                existing_user = supabase.table('users').select('username').eq('username', username).execute()
                if existing_user.data:
                    errors.append(f"Line {i}: Username '{username}' already exists")
                    continue
                
                # Create user
                user_data = {
                    'username': username,
                    'password_hash': generate_password_hash(password),
                    'email': email,
                    'role': 'student' if import_type == 'students' else 'teacher',
                    'approval_status': 'approved',  # Auto-approve for school admins
                    'school_id': user['school_id'],
                    'created_at': datetime.now().isoformat()
                }
                
                if import_type == 'students' and grade:
                    user_data['grade'] = grade
                
                result = supabase.table('users').insert(user_data).execute()
                if result.data:
                    imported_count += 1
                else:
                    errors.append(f"Line {i}: Failed to create user '{username}'")
            
            if imported_count > 0:
                flash(f'Successfully imported {imported_count} users!', 'success')
            if errors:
                flash_errors = '\n'.join(errors[:5])  # Show first 5 errors
                if len(errors) > 5:
                    flash_errors += f'\n... and {len(errors) - 5} more errors'
                flash(f'Import completed with errors:\n{flash_errors}', 'warning')
            
            return redirect(url_for('school_admin_dashboard'))
        
        return render_template('bulk_import.html')
        
    except Exception as e:
        logger.error(f"Bulk import error: {e}")
        flash('Error during bulk import.', 'danger')
        return redirect(url_for('school_admin_dashboard'))

@app.route('/school/admin/settings', methods=['GET', 'POST'])
@school_admin_required
def school_settings():
    """School settings management"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('school_admin_dashboard'))
    
    try:
        # Get current user and school
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or not user.get('is_admin'):
            flash('School admin access required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        school_response = supabase.table('schools').select('*').eq('id', user['school_id']).execute()
        school = school_response.data[0] if school_response.data else None
        
        if request.method == 'POST':
            school_name = request.form.get('school_name', '').strip()
            contact_person = request.form.get('contact_person', '').strip()
            contact_phone = request.form.get('contact_phone', '').strip()
            
            if school_name:
                # Update school info
                update_data = {'name': school_name}
                if contact_person:
                    update_data['contact_person'] = contact_person
                if contact_phone:
                    update_data['contact_phone'] = contact_phone
                
                result = supabase.table('schools').update(update_data).eq('id', user['school_id']).execute()
                if result.data:
                    flash('School settings updated successfully!', 'success')
                    return redirect(url_for('school_admin_dashboard'))
                else:
                    flash('Failed to update school settings.', 'danger')
            else:
                flash('School name is required.', 'danger')
        
        return render_template('school_settings.html', school=school)
        
    except Exception as e:
        logger.error(f"School settings error: {e}")
        flash('Error loading school settings.', 'danger')
        return redirect(url_for('school_admin_dashboard'))

@app.route('/super/admin')
@super_admin_required
def super_admin_dashboard():
    """Professional super admin dashboard"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get all schools
        schools_response = supabase.table('schools').select('*').execute()
        schools = schools_response.data if schools_response.data else []
        
        # Get all users for platform stats
        users_response = supabase.table('users').select('*').execute()
        all_users = users_response.data if users_response.data else []
        
        # Calculate stats safely
        pending_schools = [s for s in schools if s.get('status') == 'pending']
        active_schools = [s for s in schools if s.get('status') == 'active']
        
        stats = {
            'total_schools': len(schools),
            'pending_schools': len(pending_schools),
            'active_schools': len(active_schools),
            'total_users': len(all_users),
            'active_sessions': 0,
            'storage_used': '0 GB'
        }
        
        # Get recent schools (last 5)
        recent_schools = sorted(schools, key=lambda x: x.get('created_at', ''), reverse=True)[:5]
        
        return render_template('super_admin_dashboard.html',
                             stats=stats,
                             recent_schools=recent_schools)
                             
    except Exception as e:
        logger.error(f"Super admin dashboard error: {e}")
        flash(f'Error loading dashboard: {str(e)}', 'danger')
        return render_template('super_admin_dashboard.html',
                             stats={'total_schools': 0, 'pending_schools': 0, 'active_schools': 0, 'total_users': 0, 'active_sessions': 0, 'storage_used': '0 GB'},
                             recent_schools=[])

# Add placeholder routes for the missing endpoints
@app.route('/super/admin/users')
@super_admin_required
def super_admin_users():
    """Placeholder - Platform users management"""
    return "Platform Users Management - Coming Soon"

@app.route('/super/admin/analytics')
@super_admin_required  
def super_admin_analytics():
    """Placeholder - Platform analytics"""
    return "Platform Analytics - Coming Soon"

@app.route('/super/admin/approvals')
@super_admin_required
def super_admin_approvals():
    """Super admin view of ALL pending users across all schools"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_dashboard'))
    
    try:
        # Get ALL pending users from ALL schools
        pending_users = supabase.table('users').select('*, schools(name)').eq('approval_status', 'pending').execute()
        
        # Get ALL users for reference
        all_users = supabase.table('users').select('*, schools(name)').order('created_at', desc=True).execute()
        
        return render_template('super_admin_approvals.html',
                             pending_users=pending_users.data if pending_users.data else [],
                             all_users=all_users.data if all_users.data else [])
    except Exception as e:
        logger.error(f"Super admin approvals error: {e}")
        flash('Error loading user approvals.', 'danger')
        return redirect(url_for('super_admin_dashboard'))

# Also update the approve_user route to work for super admin
@app.route('/super/admin/approve_user/<username>', methods=['POST'])
@super_admin_required
def super_approve_user(username):
    """Super admin approval for any user"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_approvals'))
    
    try:
        # Update user approval status to 'approved'
        result = supabase.table('users').update({'approval_status': 'approved'}).eq('username', username).execute()
        
        if result.data:
            flash(f'✅ User {username} has been approved successfully!', 'success')
        else:
            flash('User not found.', 'warning')
    except Exception as e:
        logger.error(f"Super approve user error: {e}")
        flash('Error approving user.', 'danger')
    
    return redirect(url_for('super_admin_approvals'))

if __name__ == '__main__':
    app.run(debug=True)